#!/usr/bin/env python3

import os
import sys
import logging
import json
import yaml
import re
import glob
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import requests
from github import Github, GithubException


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


class RulesetManager:
    """Manages repository rulesets including branch and tag rules"""

    def __init__(self, logger, token):
        self.logger = logger
        self.token = token

    def create_ruleset(self, repo, ruleset_params: dict) -> bool:
        """
        Create a ruleset using GitHub's REST API

        Args:
            repo: GitHub repository object
            ruleset_params: Dictionary containing ruleset configuration
        """
        try:
            # Use the token passed through from initialization
            api_url = f"https://api.github.com/repos/{repo.organization.login}/{repo.name}/rulesets"

            headers = {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            self.logger.info(f"Ruleset: {ruleset_params}")
            response = requests.post(api_url, headers=headers, json=ruleset_params)

            if response.status_code not in (200, 201):
                self.logger.error(f"Failed to create ruleset: {response.status_code} - {response.text}")
                return False

            self.logger.info(f"Successfully created ruleset {ruleset_params['name']}")
            return True

        except Exception as e:
            self.logger.error(f"Error creating ruleset: {str(e)}")
            return False

    def configure_ruleset(self, ruleset_config: Dict[str, Any]) -> Dict[str, Any]:
        """Configure a single ruleset with all rules"""
        try:
            name = ruleset_config.get("name")
            target = ruleset_config.get("target", "branch")
            enforcement = ruleset_config.get("enforcement", "active")

            ruleset_params = {
                "name": name,
                "target": target,
                "enforcement": enforcement,
                "bypass_actors": ruleset_config.get("bypass_actors", []),
                "conditions": self._prepare_conditions(ruleset_config.get("conditions", {})),
                "rules": self._prepare_rules(ruleset_config.get("rules", [])),
            }

            return ruleset_params

        except Exception as e:
            self.logger.error(f"Error configuring ruleset {name}: {str(e)}")
            raise

    def _prepare_conditions(self, conditions: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare ruleset conditions"""
        prepared_conditions = {}

        if "ref_name" in conditions:
            prepared_conditions["ref_name"] = {
                "include": conditions["ref_name"].get("include", []),
                "exclude": conditions["ref_name"].get("exclude", []),
            }

        return prepared_conditions

    def _prepare_rules(self, rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prepare ruleset rules with their parameters"""
        prepared_rules = []

        for rule in rules:
            rule_type = rule.get("type")
            if not rule_type:
                continue

            prepared_rule = {"type": rule_type}

            if "parameters" in rule:
                prepared_rule["parameters"] = self._get_rule_parameters(rule_type, rule["parameters"])

            prepared_rules.append(prepared_rule)

        return prepared_rules

    def _get_rule_parameters(self, rule_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get parameters for specific rule types"""
        if rule_type == "pull_request":
            return {
                "dismiss_stale_reviews_on_push": params.get("dismiss_stale_reviews_on_push", True),
                "require_code_owner_review": params.get("require_code_owner_review", True),
                "require_last_push_approval": params.get("require_last_push_approval", True),
                "required_approving_review_count": params.get("required_approving_review_count", 1),
                "required_review_thread_resolution": params.get("required_review_thread_resolution", True),
            }
        if rule_type == "required_status_checks":
            return {
                "strict_required_status_checks_policy": params.get("strict_required_status_checks_policy", True),
                "required_status_checks": params.get("required_status_checks", []),
            }
        # Add other rule type parameters as needed
        return params


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
        repo_name = config.get("name")
        if not repo_name:
            self.logger.error("Repository name is required")
            return None

        try:
            # Check if repository already exists
            if self.repo_exists(repo_name):
                self.logger.info(f"Repository {repo_name} already exists, skipping creation")
                return self.org.get_repo(repo_name)

            # Create new repository
            visibility = config.get("visibility", "private").lower()
            repo = self.org.create_repo(
                name=repo_name, private=(visibility != "public"), visibility=visibility, auto_init=True
            )
            self.logger.info(f"Created new repository {repo_name}")

            # Apply settings to the new repository
            self.update_repository_settings(repo, config)
            return repo

        except GithubException as e:
            self.logger.error(f"GitHub API error while creating repository {repo_name}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error creating repository {repo_name}: {e}")
            raise

    def update_repository(self, repo_name: str, config: Dict[str, Any]) -> Optional[Any]:
        """Update an existing GitHub repository with new configuration."""
        try:
            # Get existing repository
            repo = self.org.get_repo(repo_name)

            # Verify repository name matches config
            if config.get("name") != repo_name:
                raise ValueError(
                    f"Repository name in config ({config.get('name')}) does not match expected name ({repo_name})"
                )

            # Update repository settings
            self.update_repository_settings(repo, config)
            return repo

        except GithubException as e:
            self.logger.error(f"GitHub API error while updating repository {repo_name}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error updating repository {repo_name}: {e}")
            raise

    def update_repository_settings(self, repo, config: Dict[str, Any]) -> None:
        """Update repository settings based on configuration."""
        if not repo:
            raise ValueError("Repository object is required")

        try:
            # Update basic settings
            repo.edit(
                has_issues=config.get("has_issues", True),
                has_projects=config.get("has_projects", True),
                has_wiki=config.get("has_wiki", True),
                allow_squash_merge=config.get("allow_squash_merge", True),
                allow_merge_commit=config.get("allow_merge_commit", True),
                allow_rebase_merge=config.get("allow_rebase_merge", True),
                allow_auto_merge=config.get("allow_auto_merge", False),
                delete_branch_on_merge=config.get("delete_branch_on_merge", True),
                allow_update_branch=config.get("allow_update_branch", True),
            )

            # Apply security settings
            security_config = config.get("security", {})
            if security_config.get("enableVulnerabilityAlerts", True):
                try:
                    repo.enable_vulnerability_alert()
                except Exception as e:
                    self.logger.warning(f"Could not enable vulnerability alerts: {e}")

            if security_config.get("enableAutomatedSecurityFixes", True):
                try:
                    repo.enable_automated_security_fixes()
                except Exception as e:
                    self.logger.warning(f"Could not enable automated security fixes: {e}")

            # Set topics
            topics = config.get("topics", [])
            if topics:
                try:
                    repo.replace_topics(topics)
                except Exception as e:
                    self.logger.warning(f"Could not set repository topics: {e}")

            # Apply rulesets
            if "rulesets" in config:
                self.apply_rulesets(repo, config["rulesets"])

            self.logger.info(f"Applied settings to repository {repo.name}")

        except Exception as e:
            self.logger.warning(f"Could not apply all repository settings: {e}")
            raise

    def apply_rulesets(self, repo, rulesets: List[Dict[str, Any]]) -> None:
        """Apply rulesets to a repository."""
        try:
            for ruleset_config in rulesets:
                ruleset_name = ruleset_config.get("name")
                if not ruleset_name:
                    continue

                # Configure ruleset
                ruleset_params = self.ruleset_manager.configure_ruleset(ruleset_config)

                # Create ruleset
                success = self.ruleset_manager.create_ruleset(repo, ruleset_params)

                if success:
                    self.logger.info(f"Created ruleset {ruleset_name} for repository {repo.name}")
                else:
                    self.logger.error(f"Failed to create ruleset {ruleset_name} for repository {repo.name}")

        except Exception as e:
            self.logger.error(f"Error applying rulesets: {str(e)}")
            raise


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


def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger(__name__)

    # Get environment variables
    github_token = os.environ.get("GITHUB_TOKEN")
    github_org = os.environ.get("GITHUB_ORGANIZATION")
    workspace = os.environ.get("GITHUB_WORKSPACE", os.getcwd())
    sync_mode = os.environ.get("SYNC_MODE", "changed").lower()  # "changed" or "all"

    if not all([github_token, github_org]):
        logger.error("Missing required environment variables GITHUB_TOKEN or GITHUB_ORGANIZATION")
        sys.exit(1)

    try:
        # Get repository configuration files to process
        if sync_mode == "all":
            config_files = get_all_repository_configs()
        else:
            config_files = get_changed_files()

        if not config_files:
            logger.info("No repository configuration files to process")
            sys.exit(0)

        # Initialize the GitHub repository manager
        repo_manager = GitHubRepositoryManager(github_token, github_org)

        # Process each configuration file
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

            except Exception as e:
                logger.error(f"Error processing repository {repo_name}: {e}", exc_info=True)
                # Continue processing other repositories

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
