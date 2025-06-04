#!/usr/bin/env python3

import os
import sys
import logging
import json
import glob
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
import time
import yaml
import requests
from github import Github, GithubException


def _get_bool_value(config: Dict[str, Any], key: str, default: bool) -> bool:
    """
    Get a boolean value from configuration dictionary, with fallback to default.
    Ensures the return value is always a boolean, never None.
    """
    value = config.get(key)
    if value is None:
        return default
    return bool(value)


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


class RulesetManager:
    """Manages repository rulesets including branch and tag rules"""

    def __init__(self, logger, token):
        self.logger = logger
        self.token = token

    def create_ruleset(self, repo, ruleset_params: dict) -> Dict[str, Any]:
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

            # Log the ruleset being created
            ruleset_name = ruleset_params.get("name", "unnamed")
            self.logger.info(f"Creating ruleset '{ruleset_name}': {json.dumps(ruleset_params, indent=2)}")

            response = requests.post(api_url, headers=headers, json=ruleset_params)

            if response.status_code not in (200, 201):
                error_msg = f"Failed to create ruleset '{ruleset_name}': {response.status_code} - {response.text}"
                self.logger.error(error_msg)
                return {"success": False, "message": error_msg}

            self.logger.info(f"Successfully created ruleset {ruleset_params['name']}")
            return {"success": True, "message": f"Successfully created ruleset '{ruleset_name}'"}

        except Exception as e:
            error_msg = f"Error creating ruleset '{ruleset_params.get('name', 'unnamed')}': {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "message": error_msg}

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
            # Ensure include and exclude are proper lists, not strings
            includes = conditions["ref_name"].get("include", [])
            excludes = conditions["ref_name"].get("exclude", [])

            # Handle case where include/exclude might be a string instead of a list
            if isinstance(includes, str):
                includes = self._parse_branch_targets(includes)

            if isinstance(excludes, str):
                excludes = self._parse_branch_targets(excludes)

            # Format branch references and filter out invalid ones
            prepared_includes = []
            for ref in includes:
                if ref and isinstance(ref, str):
                    # Skip entries with spaces which GitHub API rejects
                    if " " in ref.strip():
                        self.logger.warning(f"Skipping invalid branch reference with spaces: '{ref}'")
                        continue

                    if not ref.startswith("refs/"):
                        ref = f"refs/heads/{ref}"
                    prepared_includes.append(ref)

            prepared_excludes = []
            for ref in excludes:
                if ref and isinstance(ref, str):
                    if " " in ref.strip():
                        self.logger.warning(f"Skipping invalid branch reference with spaces: '{ref}'")
                        continue

                    if not ref.startswith("refs/"):
                        ref = f"refs/heads/{ref}"
                    prepared_excludes.append(ref)

            prepared_conditions["ref_name"] = {
                "include": prepared_includes,
                "exclude": prepared_excludes,
            }

            # Validate that we have at least one valid include pattern
            if not prepared_includes:
                self.logger.warning("No valid include patterns found, adding default 'refs/heads/main'")
                prepared_conditions["ref_name"]["include"] = ["refs/heads/main"]

        return prepared_conditions

    def _parse_branch_targets(self, content: str) -> List[str]:
        """Parse branch targets, handling different formats."""
        if not content:
            return []

        targets = []

        # Check if the content is a YAML-style list
        if content.strip().startswith("- "):
            for line in content.strip().split("\n"):
                if line.strip().startswith("- "):
                    branch = line[1:].strip()
                    if branch:
                        targets.append(branch)
        else:
            # Handle comma-separated or space-separated formats
            for item in content.split(","):
                branch = item.strip()
                if branch:
                    targets.append(branch)

        return targets

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

            # Check if a template repository is specified
            template_repo_name = config.get("template")

            # Ensure we have visibility set - default to private if not specified
            visibility = config.get("visibility", "private").lower()
            self.logger.info(f"Creating repository with visibility: {visibility}")

            if isinstance(template_repo_name, str) and template_repo_name.lower() != "none":
                self.logger.info(f"Creating repository {repo_name} from template {template_repo_name}")
                try:
                    # Get the template repository to verify it exists
                    self.org.get_repo(template_repo_name)  # Just verify it exists, no need to store

                    # Use the GitHub REST API directly to generate repository from template
                    api_url = f"https://api.github.com/repos/{self.org.login}/{template_repo_name}/generate"

                    headers = {
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {self.github_token}",
                        "X-GitHub-Api-Version": "2022-11-28",
                    }

                    payload = {
                        "owner": self.org.login,
                        "name": repo_name,
                        "description": config.get("description", ""),  # Ensure description is included
                        "private": True,  # Always create as private initially
                        "include_all_branches": False,
                    }

                    # Log the payload for debugging
                    self.logger.info(f"Template creation payload: {json.dumps(payload)}")

                    self.logger.info(f"Making API request to create repository from template: {api_url}")
                    response = requests.post(api_url, headers=headers, json=payload)

                    if response.status_code in (201, 200):
                        self.logger.info(
                            f"Successfully created repository {repo_name} from template {template_repo_name}"
                        )
                        # Wait briefly for repository to be fully created
                        time.sleep(2)
                        # Get the newly created repository
                        repo = self.org.get_repo(repo_name)

                        # Make sure visibility is applied properly after template creation
                        if visibility != "private":
                            self.logger.info(f"Updating repository {repo_name} to {visibility} visibility")
                            repo.edit(visibility=visibility)
                    else:
                        self.logger.error(
                            f"Failed to create repository from template: {response.status_code} - {response.text}"
                        )
                        raise GithubException(response.status_code, f"GitHub API returned: {response.text}")

                except Exception as e:
                    self.logger.error(f"Failed to create repository from template: {str(e)}")

                    # Fall back to regular creation if template doesn't exist or other issues
                    self.logger.info("Falling back to standard repository creation")
                    repo = self.org.create_repo(
                        name=repo_name, private=(visibility != "public"), visibility=visibility, auto_init=True
                    )
            else:
                # Create new repository without template
                repo = self.org.create_repo(
                    name=repo_name,
                    description=config.get("description", ""),  # Explicitly pass description
                    private=(visibility != "public"),
                    visibility=visibility,
                    auto_init=True,
                )
                self.logger.info(
                    f"Created new repository {repo_name} with visibility {visibility} and description '{config.get('description', '')}'"
                )

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

    def _update_basic_repo_settings(self, repo, config: Dict[str, Any]) -> bool:
        """Update basic repository settings from configuration."""
        update_params = {}
        settings_changed = False

        # List of all possible repository settings
        repo_settings = [
            "has_issues",
            "has_projects",
            "has_wiki",
            "has_discussions",
            "allow_squash_merge",
            "allow_merge_commit",
            "allow_rebase_merge",
            "allow_auto_merge",
            "delete_branch_on_merge",
            "allow_update_branch",
        ]

        # Check each setting and only include if explicitly defined in config
        for setting in repo_settings:
            if setting in config:
                current_value = getattr(repo, setting, None)
                new_value = config[setting]
                if current_value != new_value:
                    self.logger.info(f"Updating {setting}: {current_value} -> {new_value}")
                    update_params[setting] = new_value
                    settings_changed = True
                else:
                    self.logger.debug(f"Skipping {setting} (unchanged): {current_value}")

        # Only call edit if there are parameters to update
        if update_params:
            self.logger.info(f"Updating repository settings: {update_params}")
            repo.edit(**update_params)

        return settings_changed

    def _update_repository_metadata(self, repo, config: Dict[str, Any]) -> bool:
        """Update repository description and visibility."""
        settings_changed = False

        # Debug log to help diagnose description issues
        self.logger.info(
            f"Description in config: '{config.get('description', '<not set>')}', Current description: '{repo.description}'"
        )

        # Handle description separately as it's a common field to update
        if "description" in config and config["description"] != repo.description:
            # Always update description if it's explicitly set in config, even if empty
            self.logger.info(f"Updating description: '{repo.description}' -> '{config['description']}'")
            repo.edit(description=config["description"])
            settings_changed = True

        # Handle visibility separately
        if "visibility" in config:
            visibility = config["visibility"].lower()
            if repo.visibility != visibility:
                self.logger.info(f"Updating visibility: {repo.visibility} -> {visibility}")
                repo.edit(visibility=visibility)
                settings_changed = True

        return settings_changed

    def _update_security_settings(self, repo, security_config: Dict[str, Any]) -> bool:
        """Update repository security settings."""
        settings_changed = False

        # Only enable vulnerability alerts if explicitly set to True
        if "enableVulnerabilityAlerts" in security_config:
            should_enable = security_config["enableVulnerabilityAlerts"]
            try:
                if should_enable:
                    self.logger.info("Enabling vulnerability alerts")
                    repo.enable_vulnerability_alert()
                    settings_changed = True
                else:
                    self.logger.info("Disabling vulnerability alerts")
                    repo.disable_vulnerability_alert()
                    settings_changed = True
            except Exception as e:
                self.logger.warning(f"Could not update vulnerability alerts: {e}")

        # Only enable automated security fixes if explicitly set to True
        if "enableAutomatedSecurityFixes" in security_config:
            should_enable = security_config["enableAutomatedSecurityFixes"]
            try:
                if should_enable:
                    self.logger.info("Enabling automated security fixes")
                    repo.enable_automated_security_fixes()
                    settings_changed = True
                else:
                    self.logger.info("Disabling automated security fixes")
                    repo.disable_automated_security_fixes()
                    settings_changed = True
            except Exception as e:
                self.logger.warning(f"Could not update automated security fixes: {e}")

        return settings_changed

    def _update_topics(self, repo, topics: List[str]) -> bool:
        """Update repository topics."""
        settings_changed = False
        current_topics = repo.get_topics()

        if set(topics) != set(current_topics):
            self.logger.info(f"Updating topics: {current_topics} -> {topics}")
            try:
                repo.replace_topics(topics)
                settings_changed = True
            except Exception as e:
                self.logger.warning(f"Could not set repository topics: {e}")
        else:
            self.logger.debug("Topics already match configuration, skipping update")

        return settings_changed

    def update_repository_settings(self, repo, config: Dict[str, Any]) -> Dict[str, Any]:
        """Update repository settings based on configuration."""
        if not repo:
            raise ValueError("Repository object is required")

        results = {"settings_changed": False, "ruleset_results": [], "errors": []}

        try:
            # Track whether any settings were changed
            settings_changed = False

            # Update basic repository settings
            settings_changed |= self._update_basic_repo_settings(repo, config)

            # Update repository metadata (description, visibility)
            settings_changed |= self._update_repository_metadata(repo, config)

            # Apply security settings only if explicitly defined
            security_config = config.get("security", {})
            if security_config:
                settings_changed |= self._update_security_settings(repo, security_config)

            # Set topics only if explicitly defined
            if "topics" in config:
                # Filter out "_No response_" values
                clean_topics = [topic for topic in config["topics"] if topic != "_No response_"]
                settings_changed |= self._update_topics(repo, clean_topics)

            results["settings_changed"] = settings_changed

            # Apply rulesets only if defined in config
            if "rulesets" in config:
                # First fetch existing rulesets to avoid recreating identical ones
                existing_rulesets = self._get_current_rulesets(repo)
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

    def _get_current_rulesets(self, repo):
        """Get current rulesets for repository to compare with config"""
        try:
            api_url = f"https://api.github.com/repos/{repo.organization.login}/{repo.name}/rulesets"
            headers = {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.github_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            response = requests.get(api_url, headers=headers)

            if response.status_code == 200:
                return response.json()
            self.logger.warning(f"Could not fetch existing rulesets: {response.status_code}")
            return []
        except Exception as e:
            self.logger.warning(f"Error fetching rulesets: {e}")
            return []

    def _apply_rulesets_selectively(self, repo, new_rulesets, existing_rulesets):
        """Apply rulesets only if they differ from existing ones"""
        ruleset_results = []
        applied_count = 0
        skipped_count = 0

        # If no rulesets are provided, log a warning but don't fail
        if not new_rulesets:
            self.logger.warning(f"No rulesets provided for repository {repo.name}")
            return [{"name": "none", "success": True, "message": "No rulesets were provided to apply"}]

        self.logger.info(f"Processing {len(new_rulesets)} rulesets for {repo.name}")

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

            # Only create if no matching ruleset exists or if configuration differs
            if not matching_ruleset or self._ruleset_needs_update(matching_ruleset, ruleset_params):
                self.logger.info(f"Creating or updating ruleset {ruleset_name}")
                result = self.ruleset_manager.create_ruleset(repo, ruleset_params)
                applied_count += 1
                ruleset_results.append(
                    {
                        "name": ruleset_name,
                        "success": result.get("success", False),
                        "message": result.get("message", "Unknown result"),
                    }
                )
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

        self.logger.info(f"Ruleset application complete: {applied_count} applied, {skipped_count} skipped")
        return ruleset_results

    def _ruleset_needs_update(self, existing_ruleset, new_ruleset):
        """Compare ruleset configurations to determine if update is needed"""
        # Compare basic attributes
        for key in ["target", "enforcement"]:
            if existing_ruleset.get(key) != new_ruleset.get(key):
                return True

        # Compare conditions if they exist in both
        if "conditions" in existing_ruleset and "conditions" in new_ruleset:
            # Compare ref_name conditions carefully
            if "ref_name" in existing_ruleset.get("conditions", {}) and "ref_name" in new_ruleset.get("conditions", {}):
                existing_includes = set(existing_ruleset["conditions"]["ref_name"].get("include", []))
                new_includes = set(new_ruleset["conditions"]["ref_name"].get("include", []))
                if existing_includes != new_includes:
                    return True

                existing_excludes = set(existing_ruleset["conditions"]["ref_name"].get("exclude", []))
                new_excludes = set(new_ruleset["conditions"]["ref_name"].get("exclude", []))
                if existing_excludes != new_excludes:
                    return True

        # Compare rules if they exist in both
        if "rules" in existing_ruleset and "rules" in new_ruleset:
            if len(existing_ruleset["rules"]) != len(new_ruleset["rules"]):
                return True

            # Compare rule types and parameters
            existing_rules_by_type = {r.get("type"): r for r in existing_ruleset["rules"] if "type" in r}
            new_rules_by_type = {r.get("type"): r for r in new_ruleset["rules"] if "type" in r}

            # Check for different rule types
            if set(existing_rules_by_type.keys()) != set(new_rules_by_type.keys()):
                return True

            # Check for different parameters in rules
            for rule_type, new_rule in new_rules_by_type.items():
                if rule_type in existing_rules_by_type:
                    existing_rule = existing_rules_by_type[rule_type]

                    # Compare parameters if they exist
                    if "parameters" in new_rule and "parameters" in existing_rule:
                        if new_rule["parameters"] != existing_rule["parameters"]:
                            return True
                    elif "parameters" in new_rule or "parameters" in existing_rule:
                        # One has parameters, the other doesn't
                        return True

        # No significant differences found
        return False

    def apply_rulesets(self, repo, rulesets: List[Dict[str, Any]]) -> None:
        """Apply rulesets to a repository."""
        try:
            # Get current rulesets to avoid unnecessary updates
            existing_rulesets = self._get_current_rulesets(repo)
            self._apply_rulesets_selectively(repo, rulesets, existing_rulesets)
        except Exception as e:
            self.logger.error(f"Error applying rulesets: {str(e)}")
            raise

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
