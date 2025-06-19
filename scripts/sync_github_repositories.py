#!/usr/bin/env python3

import os
import sys
import logging
import json
import glob
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml
from github import Github, GithubException

# Import from local modules
from ruleset_manager import RulesetManager
from repository_operations import (
    create_repository,
    update_repository,
    update_basic_repo_settings,
    update_repository_metadata,
    update_security_settings,
    update_topics,
)


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


class GitHubRepositoryManager:
    """Handles GitHub repository creation, updates, and configuration management"""

    def __init__(self, github_token, organization):
        self.github_token = github_token
        self.g = Github(github_token)
        self.org = self.g.get_organization(organization)

        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("github_repositories.log")],
        )
        self.logger = logging.getLogger(__name__)

        # Set up ruleset manager
        self.ruleset_manager = RulesetManager(self.logger, self.github_token)

    def load_config(self, config_path: str) -> Dict[str, Any]:
        """Load repository configuration from file."""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                return config.get("repository", {})
        except Exception as e:
            self.logger.error(f"Error loading repository configuration from {config_path}: {e}")
            raise

    def repo_exists(self, repo_name: str) -> bool:
        """Check if a repository already exists."""
        try:
            self.org.get_repo(repo_name)
            return True
        except GithubException as e:
            if e.status == 404:
                return False
            raise

    def create_repository(self, config: Dict[str, Any]) -> Optional[Any]:
        """Create a new GitHub repository with the specified configuration."""
        return create_repository(self, config)

    def update_repository(self, repo_name: str, config: Dict[str, Any]) -> Optional[Any]:
        """Update an existing GitHub repository with new configuration."""
        return update_repository(self, repo_name, config)

    def update_repository_settings(self, repo, config: Dict[str, Any]) -> Dict[str, Any]:
        """Update repository settings based on configuration."""
        if not repo:
            raise ValueError("Repository object is required")

        results = {"settings_changed": False, "ruleset_results": [], "errors": []}

        try:
            # Track whether any settings were changed
            settings_changed = False

            # Update basic repository settings
            settings_changed |= update_basic_repo_settings(self.logger, repo, config)

            # Update repository metadata (description, visibility)
            settings_changed |= update_repository_metadata(self.logger, repo, config)

            # Apply security settings only if explicitly defined
            security_config = config.get("security", {})
            if security_config:
                settings_changed |= update_security_settings(self.logger, repo, security_config)

            # Set topics only if explicitly defined
            if "topics" in config:
                # Filter out "_No response_" values
                clean_topics = [topic for topic in config["topics"] if topic != "_No response_"]
                settings_changed |= update_topics(self.logger, repo, clean_topics)

            results["settings_changed"] = settings_changed

            # Apply rulesets only if defined in config
            if "rulesets" in config:
                # First fetch existing rulesets to avoid recreating identical ones
                existing_rulesets = self.ruleset_manager.get_current_rulesets(repo)
                ruleset_results = self._apply_rulesets_selectively(repo, config["rulesets"], existing_rulesets)
                results["ruleset_results"] = ruleset_results

            # Only show "no updates" message if truly nothing was changed
            if not settings_changed and not results.get("ruleset_results"):
                self.logger.info("No repository settings need to be updated")
            else:
                self.logger.info(f"Finished applying settings to repository {repo.name}")

            # Store sync results in the repo object for later access
            repo._sync_results = results

            return results

        except Exception as e:
            error_msg = f"Could not apply all repository settings: {e}"
            self.logger.warning(error_msg)
            results["errors"].append(error_msg)
            return results

    def _apply_rulesets_selectively(self, repo, new_rulesets, existing_rulesets):
        """Apply rulesets only if they differ from existing ones"""
        ruleset_results = []
        applied_count = 0
        skipped_count = 0
        updated_count = 0
        deleted_count = 0

        # If no rulesets are provided, log a warning but don't fail
        if not new_rulesets:
            self.logger.warning(f"No rulesets provided for repository {repo.name}")
            new_rulesets = []  # Ensure it's an empty list, not None

        self.logger.info(f"Processing {len(new_rulesets)} rulesets for {repo.name}")

        # Track ruleset names that should exist
        new_ruleset_names = {r.get("name") for r in new_rulesets if r.get("name")}

        # First, delete rulesets that exist in GitHub but not in the configuration
        for existing_ruleset in existing_rulesets:
            existing_name = existing_ruleset.get("name")
            if existing_name and existing_name not in new_ruleset_names:
                self.logger.info(f"Deleting ruleset that is no longer in configuration: {existing_name}")
                if self.ruleset_manager.delete_ruleset(repo, existing_ruleset.get("id")):
                    deleted_count += 1
                    ruleset_results.append(
                        {
                            "name": existing_name,
                            "success": True,
                            "message": f"Ruleset deleted as it's no longer in configuration",
                        }
                    )
                else:
                    ruleset_results.append(
                        {
                            "name": existing_name,
                            "success": False,
                            "message": f"Failed to delete ruleset that's no longer in configuration",
                        }
                    )

        # Process each ruleset
        for ruleset_config in new_rulesets:
            ruleset_name = ruleset_config.get("name")
            if not ruleset_name:
                ruleset_results.append(
                    {"name": "unnamed-ruleset", "success": False, "message": "Skipped ruleset with no name"}
                )
                continue

            # Check if similar ruleset already exists
            matching_ruleset = next((r for r in existing_rulesets if r.get("name") == ruleset_name), None)

            # Configure new ruleset
            ruleset_params = self.ruleset_manager.configure_ruleset(ruleset_config)

            # First condition: if ruleset doesn't exist, create it
            if not matching_ruleset:
                self.logger.info(f"Creating new ruleset {ruleset_name}")
                result = self.ruleset_manager.create_ruleset(repo, ruleset_params)
                applied_count += 1
                ruleset_results.append(
                    {
                        "name": ruleset_name,
                        "success": result.get("success", False),
                        "message": result.get("message", "Unknown result"),
                    }
                )
            # Second condition: if ruleset exists but needs update, update it
            elif self.ruleset_manager.ruleset_needs_update(matching_ruleset, ruleset_params):
                self.logger.info(f"Updating existing ruleset {ruleset_name}")
                result = self.ruleset_manager.update_ruleset(repo, matching_ruleset.get("id"), ruleset_params)
                updated_count += 1
                ruleset_results.append(
                    {
                        "name": ruleset_name,
                        "success": result.get("success", False),
                        "message": result.get("message", "Unknown result"),
                    }
                )
            # Third condition: ruleset exists and doesn't need update, skip it
            else:
                skipped_count += 1
                ruleset_results.append(
                    {
                        "name": ruleset_name,
                        "success": True,
                        "message": "Ruleset already exists with correct configuration",
                    }
                )
                self.logger.info(f"Ruleset {ruleset_name} already exists with correct configuration, skipping")

        self.logger.info(
            f"Ruleset application complete: {applied_count} created, {updated_count} updated, "
            f"{skipped_count} skipped, {deleted_count} deleted"
        )
        return ruleset_results

    def sync_single_repository(self, repo_name: str) -> bool:
        """Sync a single repository from its configuration file."""
        repo_path = f"repositories/{repo_name}/repository.yml"
        if not os.path.exists(repo_path):
            self.logger.error(f"Repository configuration file not found: {repo_path}")
            return False

        try:
            # Load repository configuration
            config = self.load_config(repo_path)

            # Verify repository name in config matches requested name
            if config.get("name") != repo_name:
                self.logger.error(
                    f"Repository name mismatch: Requested {repo_name} but config contains {config.get('name')}"
                )
                return False

            # Check if repository exists
            if self.repo_exists(repo_name):
                # Update existing repository
                self.logger.info(f"Updating existing repository: {repo_name}")
                self.update_repository(repo_name, config)
            else:
                # Create new repository
                self.logger.info(f"Creating new repository: {repo_name}")
                self.create_repository(config)

            return True

        except Exception as e:
            self.logger.error(f"Error syncing repository {repo_name}: {str(e)}")
            return False


def get_changed_files() -> List[str]:
    """Get the list of changed repository configuration files."""
    changed_files = []

    # First try to get files from CHANGED_FILES environment variable
    changed_files_env = os.environ.get("CHANGED_FILES")
    if changed_files_env:
        changed_files.extend([f.strip() for f in changed_files_env.split("\n") if f.strip()])
        logging.info(f"Files from CHANGED_FILES env: {changed_files}")

    # Fallback to event payload if available
    if not changed_files:
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if event_path:
            try:
                with open(event_path, mode="r", encoding="utf-8") as f:
                    event_data = json.load(f)
                    logging.info(f"Processing event data for changes")

                    # Handle push event specifically
                    if "commits" in event_data:
                        for commit in event_data["commits"]:
                            changed_files.extend(commit.get("modified", []))
                            changed_files.extend(commit.get("added", []))
                            changed_files.extend(commit.get("renamed", []))
            except Exception as e:
                logging.warning(f"Error reading event data: {e}")

    # Remove duplicates and filter for repository config files
    unique_files = list(set(changed_files))
    config_files = [
        f
        for f in unique_files
        if f.startswith("repositories/")
        and f.endswith("/repository.yml")
        and os.path.exists(os.path.join(os.environ.get("GITHUB_WORKSPACE", ""), f))
    ]

    logging.info(f"Final list of repository config files to process: {config_files}")
    return config_files


def get_all_repository_configs() -> List[str]:
    """Get all repository configuration files."""
    workspace = os.environ.get("GITHUB_WORKSPACE", os.getcwd())
    pattern = os.path.join(workspace, "repositories", "*", "repository.yml")
    config_files = [os.path.relpath(f, workspace) for f in glob.glob(pattern)]
    logging.info(f"Found {len(config_files)} repository configuration files")
    return config_files


def get_single_repository_config(repo_name: str) -> Optional[str]:
    """Get configuration file for a specific repository."""
    workspace = os.environ.get("GITHUB_WORKSPACE", os.getcwd())
    repo_file = os.path.join(workspace, "repositories", repo_name, "repository.yml")

    logging.info(f"Looking for repository config at: {repo_file}")

    if os.path.exists(repo_file):
        return os.path.relpath(repo_file, workspace)

    logging.error(f"Repository config file not found: {repo_file}")
    return None


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Sync GitHub repository configurations")
    parser.add_argument("--repo", "--repository", dest="repository", help="Specific repository to sync")
    parser.add_argument("--all", action="store_true", help="Sync all repositories")
    parser.add_argument("--token", help="GitHub token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--org", help="GitHub organization", default=os.environ.get("GITHUB_ORG"))
    return parser.parse_args()


def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger(__name__)

    # Parse command line arguments
    args = parse_arguments()

    # Get environment variables
    github_token = args.token or os.environ.get("GITHUB_TOKEN")
    github_org = args.org or os.environ.get("GITHUB_ORG")
    workspace = os.environ.get("GITHUB_WORKSPACE", os.getcwd())

    # Determine sync mode from arguments
    repository_name = args.repository or os.environ.get("REPOSITORY_NAME", "")
    sync_mode = "all" if args.all else os.environ.get("SYNC_MODE", "changed").lower()

    if not all([github_token, github_org]):
        logger.error("Missing required environment variables GITHUB_TOKEN or GITHUB_ORG")
        sys.exit(1)

    logger.info(f"Running in workspace: {workspace}")
    logger.info(f"Organization: {github_org}")
    logger.info(f"Sync mode: {sync_mode}")
    if repository_name:
        logger.info(f"Repository filter: {repository_name}")

    try:
        # Initialize the GitHub repository manager
        repo_manager = GitHubRepositoryManager(github_token, github_org)

        # Handle single repository sync if specified
        if repository_name:
            logger.info(f"Syncing single repository: {repository_name}")
            config_file = get_single_repository_config(repository_name)
            if not config_file:
                logger.error(f"Repository configuration not found for: {repository_name}")
                logger.error("Please check if the repository name is correct and the configuration file exists.")
                # List available repositories to help with debugging
                available_repos = [
                    path.name
                    for path in Path(os.path.join(workspace, "repositories")).glob("*")
                    if path.is_dir() and (path / "repository.yml").exists()
                ]
                logger.info(f"Available repository configurations: {available_repos}")
                sys.exit(1)

            success = repo_manager.sync_single_repository(repository_name)
            if not success:
                logger.error(f"Failed to sync repository: {repository_name}")
                sys.exit(1)

            logger.info(f"Successfully synced repository: {repository_name}")
            sys.exit(0)

        # Get repository configuration files to process for bulk sync
        if sync_mode == "all":
            config_files = get_all_repository_configs()
        else:
            config_files = get_changed_files()

        if not config_files:
            logger.info("No repository configuration files to process")
            sys.exit(0)

        success_count = 0
        failure_count = 0

        for config_file in config_files:
            try:
                # Extract repository name from path (repositories/{repo_name}/repository.yml)
                repo_name = config_file.split("/")[1]

                # Full path to the configuration file
                config_path = os.path.join(workspace, config_file)

                logger.info(f"Processing repository: {repo_name}")

                # Load repository configuration
                config = repo_manager.load_config(config_path)

                # Check if repository exists
                if repo_manager.repo_exists(repo_name):
                    # Update existing repository
                    logger.info(f"Updating existing repository: {repo_name}")
                    repo_manager.update_repository(repo_name, config)
                else:
                    # Create new repository
                    logger.info(f"Creating new repository: {repo_name}")
                    repo_manager.create_repository(config)

                success_count += 1

            except Exception as e:
                logger.error(f"Error processing repository {repo_name}: {e}", exc_info=True)
                failure_count += 1
                # Continue processing other repositories

        logger.info(f"Sync completed: {success_count} successful, {failure_count} failed")
        if failure_count > 0:
            sys.exit(1)

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
