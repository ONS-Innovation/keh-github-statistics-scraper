"""GitHub Scraper Script

This script performs a comprehensive technology audit of GitHub repositories within an organisation.
It collects information about programming languages, infrastructure as code (IaC) usage,
repository visibility, archival status, and activity metrics.

The script:
- Authenticates with GitHub using an installation token from AWS Secrets Manager
- Queries repository data via GitHub's GraphQL API
- Analyses language usage and calculates statistics
- Tracks repository activity over different time periods
- Outputs results to a JSON file with repository details and aggregated metrics

Environment Variables Required:
    GITHUB_ORG: GitHub organisation name
    GITHUB_APP_CLIENT_ID: GitHub App client ID
    AWS_SECRET_NAME: Name of AWS secret containing GitHub credentials
    AWS_DEFAULT_REGION: AWS region for Secrets Manager
    AWS_ACCESS_KEY_ID: AWS access key
    AWS_SECRET_ACCESS_KEY: AWS secret key

Output:
    repositoryStatistics.json: Contains detailed repository data and statistics
"""

import sys
import os
import json
import logging
import datetime
import time
import queue
import threading
import functools
import boto3
from requests.exceptions import ChunkedEncodingError, RequestException
from github_api_toolkit import github_graphql_interface, get_token_as_installation

KEYWORDS_FILE = {
    "keywords": {
        "documentation": ["Confluence", "MKDocs", "Sphinx", "ReadTheDocs"],
        "cloud_services": ["AWS", "Azure", "GCP"],
        "frameworks": [
            "React",
            "Angular",
            "Vue",
            "Django",
            "Streamlit",
            "Flask",
            "Spring",
            "Hibernate",
            "Express",
            "Next.js",
            "Play",
            "Akka",
            "Lagom",
        ],
        "ci_cd": [
            "Jenkins",
            "GitHub Actions",
            "GitLab CI",
            "CircleCI",
            "Travis CI",
            "Azure DevOps",
            "Concourse",
        ],
    }
}

MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Clear any existing handlers
for handler in logger.handlers:
    logger.removeHandler(handler)

# Add stdout handler
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
logger.addHandler(stdout_handler)


def retry_on_error(max_retries=None, delay_base=1):
    """A decorator that retries a function if an exception is raised or if the response is not successful.

    Args:
        max_retries (int, optional): The number of times the function should be retried before failing.
        delay_base (int, optional): Base value for exponential backoff calculation.

    Returns:
        function: Decorated function with retry logic
    """
    if max_retries is None:
        max_retries = MAX_RETRIES

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0

            while retries < max_retries:
                try:
                    result = func(*args, **kwargs)
                    # Check if result has 'ok' attribute (like requests.Response)
                    if hasattr(result, "ok") and not result.ok:
                        raise RequestException(
                            f"Request failed with status {result.status_code}"
                        )
                    return result
                except Exception as e:
                    retries += 1
                    if retries == max_retries:
                        logger.error(f"Final retry attempt failed: {str(e)}")
                        raise

                    logger.warning(
                        f"Request failed with error: {str(e)}, attempt {retries} of {max_retries}"
                    )

                    # Exponential backoff
                    delay = delay_base * (2 ** (retries - 1))
                    logger.info(f"Waiting {delay} seconds before retrying...")
                    time.sleep(delay)
            return None

        return wrapper

    return decorator


@retry_on_error()
def make_graphql_request(ql, query, variables):
    """Make a GraphQL request

    Args:
        ql: GraphQL client
        query (str): GraphQL query
        variables (dict): Query variables

    Returns:
        requests.Response: The API response
    """
    return ql.make_ql_request(query, variables)


def find_keywords_in_file(file, keywords_list):
    """Find keywords in a file

    Args:
        file (str): File contents that you are interested in searching
        keywords_list (list): List of keywords that you want to search through the file

    Returns:
        list: List of keywords that were found in the file
    """
    keywords = []
    if file is None:
        return []

    for keyword in keywords_list:
        if (keyword.lower() in file.lower()) and (keyword.lower() not in keywords):
            keywords.append(keyword)
    return keywords


class GitHubDataProducer:
    """Producer class that fetches data from GitHub API

    Args:
        ql: The GitHub client
        org: The organisation name
        batch_size: The batch size
        data_queue: The queue that contains the repository data
    """

    def __init__(self, ql, org, batch_size, data_queue):
        self.ql = ql
        self.org = org
        self.batch_size = batch_size
        self.data_queue = data_queue
        self.cursor = None
        self.has_next_page = True
        self.repos_fetched = 0  # Track number of repos fetched

    def fetch_data(self):
        """Fetches repository data from GitHub API and puts it in the queue

        Args:
            self: The instance of the class

        Returns:
            None
        """

        logger.info(f"Starting to fetch repositories for organisation: {self.org}")
        query = """
        query($org: String!, $limit: Int!, $cursor: String) {
          organization(login: $org) {
            repositories(first: $limit, after: $cursor) {
              pageInfo {
                hasNextPage
                endCursor
              }
              nodes {
                name
                url
                visibility
                isArchived
                defaultBranchRef {
                  name
                  target {
                    ... on Commit {
                      committedDate
                      history(first: 1) {
                        nodes {
                          committedDate
                        }
                      }
                    }
                  }
                }
                languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
                  edges {
                    size
                    node {
                      name
                      color
                    }
                  }
                  totalSize
                }
                object(expression: "HEAD:") {
                  ... on Tree {
                    entries {
                      name
                      type
                      object {
                        ... on Blob {
                            text
                        }
                        ... on Tree {
                            entries {
                                name
                            }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """

        while self.has_next_page:
            variables = {
                "org": self.org,
                "limit": self.batch_size,
                "cursor": self.cursor,
            }

            try:
                logger.info(f"Fetching | Batch: {self.batch_size}")
                result = make_graphql_request(self.ql, query, variables)
                data = result.json()

                if "errors" in data:
                    logger.error(f"GraphQL query returned errors: {data['errors']}")
                    break

                repos = data["data"]["organization"]["repositories"]["nodes"]
                page_info = data["data"]["organization"]["repositories"]["pageInfo"]

                self.repos_fetched += len(repos)
                logger.info(f"Fetched: {len(repos)} | Total: {self.repos_fetched}")

                # Put the repos data in the queue
                self.data_queue.put(repos)
                logger.debug(
                    f"Added batch of {len(repos)} | Total: {self.repos_fetched}"
                )

                self.has_next_page = page_info["hasNextPage"]
                self.cursor = page_info["endCursor"]

            except Exception as e:
                logger.error(f"Error fetching repositories: {str(e)}")
                break

        # Signal that we're done producing data
        self.data_queue.put(None)
        logger.info(
            f"Completed fetching repositories. Total repositories fetched: {self.repos_fetched}"
        )


class GitHubDataConsumer:
    """Consumer class that processes repository data

    Args:
        data_queue: The queue that contains the repository data
        result_queue: The queue that contains the processed repository data
        ql: The GitHub client
        org: The organisation name
    """

    def __init__(self, data_queue, result_queue, ql, org):
        self.data_queue = data_queue
        self.result_queue = result_queue
        self.ql = ql  # GitHub client
        self.org = org  # Organization name
        self.language_stats = {}
        self.archived_language_stats = {}
        self.repos_processed = 0  # Track number of repos processed
        self.codeowners_found = 0  # Track number of CODEOWNERS files found
        self.org_teams = self.fetch_org_teams()  # Fetch all teams in the organization
        logger.info(f"Found {len(self.org_teams)} teams in organization {self.org}")

    def fetch_org_teams(self):
        """Fetch all teams from the organization

        Args:
            self: The instance of the class

        Returns:
            list: List of teams
        """
        query = f"""
            query ($org: String!) {{
                organization(login: $org) {{
                    teams(first: 100) {{
                        nodes {{
                            name
                            slug
                        }}
                    }}
                }}
            }}
        """

        try:
            variables = {"org": self.org}
            result = make_graphql_request(self.ql, query, variables)
            data = result.json()

            if "errors" in data:
                logger.error(
                    f"GraphQL query returned errors when fetching organization teams: {data['errors']}"
                )
                return []

            teams = []
            if data["data"]["organization"].get("teams") and data["data"][
                "organization"
            ]["teams"].get("nodes"):
                for team in data["data"]["organization"]["teams"]["nodes"]:
                    teams.append({"name": team.get("name"), "slug": team.get("slug")})
                logger.info(
                    f"Retrieved {len(teams)} teams from organization {self.org}"
                )
            return teams
        except Exception as e:
            logger.error(f"Error fetching teams from organization {self.org}: {str(e)}")
            return []

    def fetch_codeowners(self, repo_name, default_branch="main"):
        """Fetch CODEOWNERS file content from a repository

        Args:
            self: The instance of the class
            repo_name: The name of the repository
            default_branch: The default branch of the repository
        """
        # Try different possible locations of CODEOWNERS file
        paths = [
            "CODEOWNERS",
            ".github/CODEOWNERS",
            "docs/CODEOWNERS",
            ".gitlab/CODEOWNERS",
        ]

        for path in paths:
            query = f"""
                query ($owner: String!, $repo: String!) {{
                    repository(owner: $owner, name: $repo) {{
                        file: object(expression: "{default_branch}:{path}") {{
                            ... on Blob {{
                                text
                            }}
                        }}
                    }}
                }}
            """

            try:
                variables = {"owner": self.org, "repo": repo_name}
                result = make_graphql_request(self.ql, query, variables)
                data = result.json()

                if "errors" in data:
                    continue

                if data["data"]["repository"]["file"] is not None:
                    content = data["data"]["repository"]["file"].get("text")
                    if content:
                        self.codeowners_found += 1
                        logger.debug(f"Found CODEOWNERS file at {path} in {repo_name}")
                        return content
            except Exception as e:
                logger.error(
                    f"Error fetching CODEOWNERS from {path} in {repo_name}: {str(e)}"
                )

        return None

    def parse_codeowners(self, content):
        """Parse CODEOWNERS file to extract team names and match against org teams

        Args:
            self: The instance of the class
            content: The content of the CODEOWNERS file

        Returns:
            list: List of teams
        """
        if not content:
            return []

        # Use toolkit methods to parse CODEOWNERS
        codeowner_handles = self.ql.get_codeowners_from_text(content)
        team_user_list = self.ql.identify_teams_and_users(codeowner_handles)
        
        team_items = [item for item in team_user_list if item["type"] == "team"]
        
        org_team_lookup = {team["slug"]: team["name"] for team in self.org_teams}
        
        # Match teams using the lookup
        matched_teams = []
        for item in team_items:
            if item["name"] in org_team_lookup and org_team_lookup[item["name"]] not in matched_teams:
                matched_teams.append(org_team_lookup[item["name"]])
        
        return matched_teams

    def process_repo(self, repo):
        """Process a single repository data

        Args:
            self: The instance of the class
            repo: The repository data

        Returns:
            dict: The processed repository data
        """
        try:
            # Initialize all variables at the start
            is_archived = repo.get("isArchived", False)
            last_commit_date = None
            languages = []
            IAC = []
            ci_cd = []
            docs = []
            cloud = []
            frameworks = []
            readme_content = None
            pyproject_content = None
            package_json_content = None

            # Get default branch
            default_branch = "main"
            if repo.get("defaultBranchRef"):
                default_branch = repo["defaultBranchRef"].get("name", "main")

            # Fetch and parse CODEOWNERS file to get teams
            codeowners_content = self.fetch_codeowners(repo["name"], default_branch)
            teams = self.parse_codeowners(codeowners_content)

            # Get last commit date
            if repo.get("defaultBranchRef") and repo["defaultBranchRef"].get("target"):
                last_commit_date = repo["defaultBranchRef"]["target"].get(
                    "committedDate"
                )

            # Process languages
            if repo["languages"]["edges"]:
                total_size = repo["languages"]["totalSize"]
                for edge in repo["languages"]["edges"]:
                    lang_name = edge["node"]["name"]
                    if lang_name == "HCL":
                        IAC.append("Terraform")
                    if lang_name == "Dockerfile":
                        IAC.append("Docker")
                    percentage = (edge["size"] / total_size) * 100

                    # Choose which statistics dictionary to update based on archive status
                    stats_dict = (
                        self.archived_language_stats
                        if is_archived
                        else self.language_stats
                    )

                    # Update language statistics
                    if lang_name not in stats_dict:
                        stats_dict[lang_name] = {
                            "repo_count": 0,
                            "average_percentage": 0,
                            "total_size": 0,
                        }
                    stats_dict[lang_name]["repo_count"] += 1
                    stats_dict[lang_name]["average_percentage"] += percentage
                    stats_dict[lang_name]["total_size"] += edge["size"]

                    languages.append(
                        {
                            "name": lang_name,
                            "size": edge["size"],
                            "percentage": percentage,
                        }
                    )

            documentation_list = KEYWORDS_FILE["keywords"]["documentation"]
            cloud_services_list = KEYWORDS_FILE["keywords"]["cloud_services"]
            frameworks_list = KEYWORDS_FILE["keywords"]["frameworks"]

            if repo["object"] is not None and repo["object"]["entries"]:
                for entry in repo["object"]["entries"]:
                    # Check for file contents
                    if entry["name"].lower() == "readme.md":
                        readme_content = entry["object"]["text"]
                    elif entry["name"].lower() == "pyproject.toml":
                        pyproject_content = entry["object"]["text"]
                    elif entry["name"].lower() == "package.json":
                        package_json_content = entry["object"]["text"]
                    # Check for CI/CD configurations
                    elif entry["name"] == ".github":
                        if entry["object"]["entries"]:
                            for gh_entry in entry["object"]["entries"]:
                                if gh_entry["name"] == "workflows":
                                    ci_cd.append("GitHub Actions")
                                    break
                    elif entry["name"] == "ci":
                        if entry["object"]["entries"]:
                            for ci_entry in entry["object"]["entries"]:
                                if "pipeline.yml" in ci_entry["name"]:
                                    ci_cd.append("Concourse")
                                    break

            # Process frameworks
            frameworks_pyproject = find_keywords_in_file(
                pyproject_content, frameworks_list
            )
            frameworks_package_json = find_keywords_in_file(
                package_json_content, frameworks_list
            )
            frameworks = list(set(frameworks_pyproject + frameworks_package_json))

            # Process documentation and cloud services
            if readme_content is not None:
                for doc, cl in zip(documentation_list, cloud_services_list):
                    if doc.lower() in readme_content.lower():
                        docs.append(doc)
                    if cl.lower() in readme_content.lower():
                        cloud.append(cl)

            repo_info = {
                "name": repo["name"],
                "url": repo["url"],
                "visibility": repo["visibility"],
                "is_archived": is_archived,
                "last_commit": last_commit_date,
                "users": teams,  # Add teams from CODEOWNERS as users
                "technologies": {
                    "languages": languages,
                    "IAC": IAC,
                    "docs": docs,
                    "cloud": cloud,
                    "frameworks": frameworks,
                    "ci_cd": ci_cd,
                },
            }

            return repo_info

        except Exception as e:
            logger.error(
                f"Error processing repository {repo.get('name', 'unknown')}: {str(e)}"
            )
            return None

    def process_data(self):
        """Process repository data from the queue

        Args:
            self: The instance of the class

        Returns:
            None
        """
        logger.info("Starting repository processing")
        batch_count = 0

        while True:
            repos_batch = self.data_queue.get()
            if repos_batch is None:  # Check for termination signal
                logger.info(
                    "Received termination signal, no more repositories to process"
                )
                break

            batch_count += 1
            logger.info(
                f"Processing | Batch: {batch_count} | Repos: {len(repos_batch)}"
            )

            processed_repos = []
            for repo in repos_batch:
                logger.debug(f"Processing | Repo: {repo.get('name', 'unknown')}")
                processed_repo = self.process_repo(repo)
                if processed_repo:
                    processed_repos.append(processed_repo)
                    self.repos_processed += 1

            logger.info(f"Batch #{batch_count} | Processed: {len(processed_repos)}")
            logger.info(f"CODEOWNERS: {self.codeowners_found}")
            self.result_queue.put(processed_repos)

        # Signal that we're done processing
        self.result_queue.put(None)
        logger.info(
            f"Completed | Repos: {self.repos_processed} | CODEOWNERS: {self.codeowners_found}"
        )


def get_repository_technologies(ql, org, batch_size=5):
    """Get technology information for all repositories in an organisation using threads

    Args:
        ql: The GitHub client
        org: The organisation name
        batch_size: The batch size

    Returns:
        dict: The processed repository data
    """
    logger.info(f"Starting | Org: {org} | Batch: {batch_size}")
    data_queue = queue.Queue(maxsize=10)  # Buffer for raw data
    result_queue = queue.Queue()  # Buffer for processed results
    all_repos = []

    # Create producer and consumer instances
    producer = GitHubDataProducer(ql, org, batch_size, data_queue)
    consumer = GitHubDataConsumer(
        data_queue, result_queue, ql, org
    )  # Pass ql and org to consumer

    # Start producer thread
    logger.info("Starting producer thread for repository fetching")
    producer_thread = threading.Thread(target=producer.fetch_data)
    producer_thread.start()

    # Start consumer thread
    logger.info("Starting consumer thread for repository processing")
    consumer_thread = threading.Thread(target=consumer.process_data)
    consumer_thread.start()

    # Collect results
    logger.info("Waiting for processed repository results")
    done_consumers = 0
    result_batch_count = 0
    while done_consumers < 1:  # We only have one consumer for now
        result = result_queue.get()
        if result is None:
            logger.info("Consumer thread signaled completion")
            done_consumers += 1
        else:
            result_batch_count += 1
            logger.info(f"Batch #{result_batch_count} | Repos: {len(result)}")
            all_repos.extend(result)

    # Wait for threads to complete
    logger.info("Waiting for threads to complete")
    producer_thread.join()
    consumer_thread.join()
    logger.info(f"Completed | Repos: {len(all_repos)}")

    # Calculate statistics
    total_repos = len(all_repos)
    private_repos = sum(1 for repo in all_repos if repo["visibility"] == "PRIVATE")
    public_repos = sum(1 for repo in all_repos if repo["visibility"] == "PUBLIC")
    internal_repos = sum(1 for repo in all_repos if repo["visibility"] == "INTERNAL")
    archived_repos = sum(1 for repo in all_repos if repo["is_archived"])
    archived_private = sum(
        1
        for repo in all_repos
        if repo["is_archived"] and repo["visibility"] == "PRIVATE"
    )
    archived_public = sum(
        1
        for repo in all_repos
        if repo["is_archived"] and repo["visibility"] == "PUBLIC"
    )
    archived_internal = sum(
        1
        for repo in all_repos
        if repo["is_archived"] and repo["visibility"] == "INTERNAL"
    )

    # Calculate language averages
    language_averages = {}
    for lang, stats in consumer.language_stats.items():
        language_averages[lang] = {
            "repo_count": stats["repo_count"],
            "average_percentage": round(
                stats["average_percentage"] / stats["repo_count"], 3
            ),
            "total_size": stats["total_size"],
        }

    archived_language_averages = {}
    for lang, stats in consumer.archived_language_stats.items():
        archived_language_averages[lang] = {
            "repo_count": stats["repo_count"],
            "average_percentage": round(
                stats["average_percentage"] / stats["repo_count"], 3
            ),
            "total_size": stats["total_size"],
        }

    # Create final output
    output = {
        "repositories": all_repos,
        "stats_unarchived": {
            "total": total_repos - archived_repos,
            "private": private_repos - archived_private,
            "public": public_repos - archived_public,
            "internal": internal_repos - archived_internal,
            "active_last_month": sum(
                1
                for repo in all_repos
                if repo["last_commit"]
                and not repo["is_archived"]
                and (
                    datetime.datetime.now(datetime.timezone.utc)
                    - datetime.datetime.fromisoformat(
                        repo["last_commit"].replace("Z", "+00:00")
                    )
                ).days
                <= 30
            ),
            "active_last_3months": sum(
                1
                for repo in all_repos
                if repo["last_commit"]
                and not repo["is_archived"]
                and (
                    datetime.datetime.now(datetime.timezone.utc)
                    - datetime.datetime.fromisoformat(
                        repo["last_commit"].replace("Z", "+00:00")
                    )
                ).days
                <= 90
            ),
            "active_last_6months": sum(
                1
                for repo in all_repos
                if repo["last_commit"]
                and not repo["is_archived"]
                and (
                    datetime.datetime.now(datetime.timezone.utc)
                    - datetime.datetime.fromisoformat(
                        repo["last_commit"].replace("Z", "+00:00")
                    )
                ).days
                <= 180
            ),
        },
        "stats_archived": {
            "total": archived_repos,
            "private": archived_private,
            "public": archived_public,
            "internal": archived_internal,
            "active_last_month": sum(
                1
                for repo in all_repos
                if repo["last_commit"]
                and repo["is_archived"]
                and (
                    datetime.datetime.now(datetime.timezone.utc)
                    - datetime.datetime.fromisoformat(
                        repo["last_commit"].replace("Z", "+00:00")
                    )
                ).days
                <= 30
            ),
            "active_last_3months": sum(
                1
                for repo in all_repos
                if repo["last_commit"]
                and repo["is_archived"]
                and (
                    datetime.datetime.now(datetime.timezone.utc)
                    - datetime.datetime.fromisoformat(
                        repo["last_commit"].replace("Z", "+00:00")
                    )
                ).days
                <= 90
            ),
            "active_last_6months": sum(
                1
                for repo in all_repos
                if repo["last_commit"]
                and repo["is_archived"]
                and (
                    datetime.datetime.now(datetime.timezone.utc)
                    - datetime.datetime.fromisoformat(
                        repo["last_commit"].replace("Z", "+00:00")
                    )
                ).days
                <= 180
            ),
        },
        "language_statistics_unarchived": language_averages,
        "language_statistics_archived": archived_language_averages,
        "metadata": {
            "last_updated": datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%d"
            )
        },
    }

    return output


def get_github_client():
    """Get authenticated GitHub GraphQL client

    Args:
        None

    Returns:
        tuple: The GitHub client and the organisation name
    """
    org = os.getenv("GITHUB_ORG")
    client_id = os.getenv("GITHUB_APP_CLIENT_ID")
    secret_name = os.getenv("AWS_SECRET_NAME")
    secret_region = os.getenv("AWS_DEFAULT_REGION", "eu-west-2")

    # Set up AWS session
    session = boto3.Session()
    secret_manager = session.client("secretsmanager", region_name=secret_region)

    # Get GitHub token
    logger.info("Getting GitHub token from AWS Secrets Manager")
    secret = secret_manager.get_secret_value(SecretId=secret_name)["SecretString"]

    token = get_token_as_installation(org, secret, client_id)
    if not token:
        raise Exception("Failed to get GitHub token")

    return github_graphql_interface(str(token[0])), org


def main():
    """Main entry point for the batch job

    Args:
        None

    Returns:
        None
    """
    try:
        logger.info("Starting GitHub repository scraper")

        # Get GitHub client
        ql, org = get_github_client()

        # Get repository data
        batch_size = int(os.getenv("BATCH_SIZE", "30"))
        logger.info(f"Processing repositories with batch size: {batch_size}")

        output = get_repository_technologies(ql, org, batch_size)

        if os.getenv("ENVIRONMENT", "development").lower() == "production":
            # Save to S3
            bucket = os.getenv("SOURCE_BUCKET")
            key = os.getenv("SOURCE_KEY")

            logger.info(f"Saving results to S3: {bucket}/{key}")
            s3 = boto3.client("s3")
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(output, indent=2),
                ContentType="application/json",
            )
        else:
            with open("repositoryStatistics.json", "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)

        logger.info("Successfully completed repository scanning")

    except Exception as e:
        logger.error(f"Error in main process: {str(e)}")
        raise


if __name__ == "__main__":
    main()
