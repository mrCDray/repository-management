#!/usr/bin/env python3

import json
import copy
from typing import Dict, Any, List
import requests


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
            # Process status checks from either required_status_checks or required_status_checks_list
            status_checks = []

            # First check if there are already processed status checks
            if "required_status_checks" in params and params["required_status_checks"]:
                status_checks = params["required_status_checks"]

            # If not, check for the list format from issue forms
            elif "required_status_checks_list" in params:
                raw_checks = params["required_status_checks_list"]

                # Handle string format with hyphens
                if isinstance(raw_checks, str):
                    for line in raw_checks.strip().split("\n"):
                        line = line.strip()
                        if line.startswith("- "):
                            status_checks.append(line[2:].strip())
                        elif line:
                            status_checks.append(line.strip())
                # Handle list format
                elif isinstance(raw_checks, list):
                    for item in raw_checks:
                        if isinstance(item, str):
                            if item.strip().startswith("- "):
                                status_checks.append(item[2:].strip())
                            else:
                                status_checks.append(item.strip())

            self.logger.info(f"Using status checks: {status_checks}")

            return {
                "strict_required_status_checks_policy": params.get("strict_required_status_checks_policy", True),
                "do_not_enforce_on_create": params.get("do_not_enforce_on_create", False),
                "required_status_checks": status_checks,
            }
        # Add other rule type parameters as needed
        return params

    def get_current_rulesets(self, repo):
        """Get current rulesets for repository to compare with config"""
        try:
            api_url = f"https://api.github.com/repos/{repo.organization.login}/{repo.name}/rulesets"
            headers = {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
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

    def ruleset_needs_update(self, existing_ruleset, new_ruleset):
        """Check if a ruleset needs to be updated."""
        # Normalize ruleset configurations for comparison
        normalized_existing = self._normalize_ruleset_for_comparison(existing_ruleset)
        normalized_new = self._normalize_ruleset_for_comparison(new_ruleset)

        # Deep comparison of the normalized configurations
        return json.dumps(normalized_existing, sort_keys=True) != json.dumps(normalized_new, sort_keys=True)

    def _normalize_ruleset_for_comparison(self, ruleset):
        """Normalize ruleset for comparison by removing irrelevant fields and standardizing format."""
        # Create a copy to avoid modifying the original
        result = copy.deepcopy(ruleset)

        # Remove fields that shouldn't affect comparison
        if "id" in result:
            del result["id"]
        if "node_id" in result:
            del result["node_id"]

        # Sort lists for consistent comparison
        if "rules" in result and isinstance(result["rules"], list):
            for rule in result["rules"]:
                if "parameters" in rule and isinstance(rule["parameters"], dict):
                    # Sort lists in parameters
                    for key, value in rule["parameters"].items():
                        if isinstance(value, list):
                            rule["parameters"][key] = sorted(value)

        return result

    def update_ruleset(self, repo, ruleset_id, ruleset_params):
        """Update an existing ruleset"""
        api_url = f"https://api.github.com/repos/{repo.organization.login}/{repo.name}/rulesets/{ruleset_id}"

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        ruleset_name = ruleset_params.get("name", "unnamed")
        self.logger.info(f"Updating ruleset '{ruleset_name}' (ID: {ruleset_id})")

        response = requests.put(api_url, headers=headers, json=ruleset_params)

        if response.status_code in (200, 201):
            self.logger.info(f"Successfully updated ruleset '{ruleset_name}'")
            return {"success": True, "message": f"Successfully updated ruleset '{ruleset_name}'"}

        error_message = f"Failed to update ruleset '{ruleset_name}': {response.status_code} - {response.text}"
        self.logger.error(error_message)
        return {"success": False, "message": error_message}

    def delete_ruleset(self, repo, ruleset_id):
        """Delete a ruleset using GitHub's REST API"""
        try:
            api_url = f"https://api.github.com/repos/{repo.organization.login}/{repo.name}/rulesets/{ruleset_id}"

            headers = {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }

            self.logger.info(f"Deleting ruleset with ID: {ruleset_id}")

            response = requests.delete(api_url, headers=headers)

            if response.status_code not in (200, 201, 204):
                self.logger.error(f"Failed to delete ruleset {ruleset_id}: {response.status_code} - {response.text}")
                return False

            self.logger.info(f"Successfully deleted ruleset with ID {ruleset_id}")
            return True
        except Exception as e:
            self.logger.error(f"Error deleting ruleset {ruleset_id}: {str(e)}")
            return False
