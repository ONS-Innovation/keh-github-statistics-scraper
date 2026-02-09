# GitHub Statistics Scraper

A Python script to collect GitHub repository statistics and store them within an S3 bucket.
This repository uses the scheduled batch module to deploy the service as a batch job on AWS.

This tool is responsible for populating the Statistics page within the Digital Landscape ([View Repository](https://github.com/ONSdigital/keh-digital-landscape)).

## Disclaimer

This repository is quite old and is due a fair bit of work to bring it up to the standards of our more recent repositories.

There are a few `TODOs` scattered throughout the README and codebase that will need to be addressed.

---

## Table of Contents

- [GitHub Statistics Scraper](#github-statistics-scraper)
  - [Disclaimer](#disclaimer)
  - [Table of Contents](#table-of-contents)
  - [Prerequisites:](#prerequisites)
  - [Getting started](#getting-started)
  - [Deployment](#deployment)
    - [Deployments with Concourse](#deployments-with-concourse)
      - [Allowlisting your IP](#allowlisting-your-ip)
      - [Setting up a pipeline](#setting-up-a-pipeline)
      - [Prod deployment](#prod-deployment)
      - [Triggering a pipeline](#triggering-a-pipeline)
      - [Destroying a pipeline](#destroying-a-pipeline)
    - [Manual Deployment](#manual-deployment)
  - [Testing](#testing)
  - [Linting and formatting](#linting-and-formatting)

## Prerequisites:

- Python 3.10+
- Poetry
- AWS CLI
- Make

## Getting started

1. Install Dependencies:

    ```bash
    make install
    ```

2. Export Environment Variables

    ```bash
    # AWS
    export AWS_ACCESS_KEY_ID=<KEY>
    export AWS_SECRET_ACCESS_KEY=<SECRET>
    export AWS_DEFAULT_REGION=<REGION>
    export AWS_SECRET_NAME=/<env>/github-tooling-suite/<onsdigital/ons-innovation>

    # GitHub
    export GITHUB_APP_CLIENT_ID=<CLIENT_ID>
    export GITHUB_ORG=<onsdigital/ons-innovation>

    # Other
    export SOURCE_BUCKET=<BUCKET_NAME>
    export SOURCE_KEY=<KEY>
    export BATCH_SIZE=<BATCH_SIZE>
    export ENVIRONMENT=<development/production>
    ```

    | Variable        | Description                                                                        |
    | --------------- | ---------------------------------------------------------------------------------- |
    | `source_bucket` | The S3 bucket that will store the output of the script.                            |
    | `source_key`    | The key of the file that will store the output of the script.                      |
    | `batch_size`    | The number of repositories that will be scraped in each batch.                     |
    | `environment`   | Determines where to save the results. `development`: locally, `production`: to S3. |

3. Run the script:

    ```bash
    make run
    ```

## Deployment

### Deployments with Concourse

#### Allowlisting your IP

To setup the deployment pipeline with concourse, you must first allowlist your IP address on the Concourse
server. IP addresses are flushed everyday at 00:00 so this must be done at the beginning of every working day
whenever the deployment pipeline needs to be used. Follow the instructions on the Confluence page (SDP Homepage > SDP Concourse > Concourse Login) to
login. All our pipelines run on sdp-pipeline-prod, whereas sdp-pipeline-dev is the account used for
changes to Concourse instance itself. Make sure to export all necessary environment variables from sdp-pipeline-prod (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN).

#### Setting up a pipeline

When setting up our pipelines, we use ecs-infra-user on sdp-dev to be able to interact with our infrastructure on AWS. The credentials for this are stored on
AWS Secrets Manager so you do not need to set up anything yourself.

To set the pipeline, run the following script:

```bash
chmod u+x ./concourse/scripts/set_pipeline.sh
./concourse/scripts/set_pipeline.sh
```

Note that you only have to run chmod the first time running the script in order to give permissions.
This script will set the branch and pipeline name to whatever branch you are currently on. It will also set the image tag on ECR to 7 characters of the current branch name if running on a branch other than main. For main, the ECR tag will be the latest release tag on the repository that has semantic versioning(vX.Y.Z).

The pipeline name itself will usually follow a pattern as follows: `github-statistics-scraper-<branch-name>` for any non-main branch and `github-statistics-scraper` for the main/master branch.

#### Prod deployment

To deploy to prod, it is required that a Github Release is made on Github. The release is required to follow semantic versioning of vX.Y.Z.

A manual trigger is to be made on the pipeline name `github-statistics-scraper > deploy-after-github-release` job through the Concourse CI UI. This will create a github-create-tag resource that is required on the `github-statistics-scraper > build-and-push-prod` job. Then the prod deployment job is also through a manual trigger ensuring that prod is only deployed using the latest GitHub release tag in the form of vX.Y.Z and is manually controlled.

#### Triggering a pipeline

Once the pipeline has been set, you can manually trigger a dev build on the Concourse UI, or run the following command for non-main branch deployment:

```bash
fly -t aws-sdp trigger-job -j github-statistics-scraper-<branch-name>/build-and-push-dev
```

and for main branch deployment:

```bash
fly -t aws-sdp trigger-job -j github-statistics-scraper/build-and-push-dev
```

#### Destroying a pipeline

To destroy the pipeline, run the following command:

```bash
fly -t aws-sdp destroy-pipeline -p github-statistics-scraper-<branch-name>
```

**It is unlikely that you will need to destroy a pipeline, but the command is here if needed.**

**Note:** This will not destroy any resources created by Terraform. You must manually destroy these resources using Terraform.

### Manual Deployment

TODO: Add manual deployment instructions for deploying the script without Concourse.

## Testing

TODO: Add testing instructions.

TODO: Add tests.

## Linting and formatting

TODO: Update linting and formatting practices to bring the repo in line with common team practices.

Install dev dependencies:
```bash
make install-dev
```

Run lint command:
```bash
make lint
```

Run ruff check:
```bash
make ruff
```

Run pylint:
```bash
make pylint
```

Run black:
```bash
make black
```
