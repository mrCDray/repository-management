#!/usr/bin/env python3

import os
import re
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Any, Tuple
import requests
import yaml
from collections import OrderedDict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("repository_processor")


class IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


# Add custom representer for lists to ensure proper indentation
def represent_list(dumper, data):
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=False)


yaml.add_representer(list, represent_list)


# Configure PyYAML to preserve dictionary order
def represent_ordereddict(dumper, data):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items())


yaml.add_representer(OrderedDict, represent_ordereddict)


def parse_issue_body(body: str) -> Dict[str, Any]:
    """Parse the issue body to extract input values."""
    logger.info("Parsing issue body")
    lines = body.split("\n")

    result = {}
    current_section = None

    for line in lines:
        if line.startswith("### "):
            current_section = line[4:].lower().replace(" ", "_")
            continue

        if current_section and line.strip():
            if (
                current_section == "topics" or current_section == "required_status_check_list"
            ) and line.strip().startswith("- "):
                if current_section not in result:
                    result[current_section] = []
                result[current_section].append(line.strip()[2:])
            elif current_section not in result:
                value = line.strip()
                # Convert string true/false to Python boolean
                if value.lower() == "true":
                    result[current_section] = True
                elif value.lower() == "false":
                    result[current_section] = False
                else:
                    result[current_section] = value

    logger.info(f"Parsed issue data: {json.dumps(result, default=str)}")
    return result


def load_default_config(repo_name: str) -> Dict[str, Any]:
    """Load default repository configuration."""
    default_config_file = "default_repository_config.yml"
    # Also try default_repository.yml for compatibility
    if not os.path.exists(default_config_file) and os.path.exists("default_repository.yml"):
        default_config_file = "default_repository.yml"

    try:
        with open(default_config_file, "r", encoding="utf-8") as f:
            default_config = yaml.safe_load(f)

            # Create a deep copy of the configuration
            config = OrderedDict(default_config.get("repository", {}))

            # Replace placeholder with actual repository name
            config["name"] = repo_name

            return config
    except Exception as e:
        logger.error(f"Error loading default repository configuration: {str(e)}")
        raise


def load_existing_config(repo_name: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load existing repository configuration if it exists."""
    repo_file = f"repositories/{repo_name}/repository.yml"

    if not os.path.exists(repo_file):
        logger.warning(f"Repository configuration does not exist: {repo_file}")
        return None, f"Repository configuration for {repo_name} does not exist."

    try:
        with open(repo_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not config or "repository" not in config:
            logger.error(f"Invalid repository config format in {repo_file}")
            return None, f"Invalid repository configuration format in {repo_file}"

        return config, None
    except Exception as e:
        logger.error(f"Failed to load repository configuration: {str(e)}")
        return None, f"Failed to load repository configuration: {str(e)}"


def create_repository_config(
    repo_name: str, issue_data: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Create a new repository configuration."""
    logger.info(f"Creating repository configuration for '{repo_name}'")

    # Check if repository config already exists
    repo_dir = f"repositories/{repo_name}"
    repo_file = f"{repo_dir}/repository.yml"

    if os.path.exists(repo_file):
        logger.warning(f"Repository configuration already exists: {repo_file}")
        return None, f"Repository configuration for {repo_name} already exists. Use 'update' action instead."

    # Load default configuration
    try:
        config = load_default_config(repo_name)
    except Exception as e:
        return None, f"Failed to load default configuration: {str(e)}"

    # Update configuration with issue data
    update_config_from_issue_data(config, issue_data)

    return {"repository": config}, None


def update_repository_config(
    repo_name: str, issue_data: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Update an existing repository configuration."""
    logger.info(f"Updating repository configuration for '{repo_name}'")

    # Load existing configuration
    config, error = load_existing_config(repo_name)
    if error:
        return None, error

    # Update configuration with issue data
    update_config_from_issue_data(config["repository"], issue_data)

    return config, None


def manage_branch_rules(repo_name: str, issue_data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Update branch protection rules for an existing repository."""
    logger.info(f"Managing branch rules for '{repo_name}'")

    # Load existing configuration
    config, error = load_existing_config(repo_name)
    if error:
        return None, error

    # Update branch protection rules
    update_branch_rules(config["repository"], issue_data)

    return config, None


def update_branch_rules(config: Dict[str, Any], issue_data: Dict[str, Any]) -> None:
    """Update repository branch protection rules based on issue data."""
    branch_name = issue_data.get("branch_name")
    if not branch_name:
        logger.warning("No branch name specified, skipping branch rule update")
        return

    # Initialize rulesets if they don't exist
    if "rulesets" not in config:
        config["rulesets"] = []

    # Check if a ruleset for this branch already exists
    branch_ruleset = None
    for i, ruleset in enumerate(config["rulesets"]):
        conditions = ruleset.get("conditions", {})
        ref_name = conditions.get("ref_name", {})
        includes = ref_name.get("include", [])

        # Check if this ruleset applies to our branch
        branch_refs = [f"refs/heads/{branch_name}"]
        if any(ref in includes for ref in branch_refs):
            branch_ruleset = ruleset
            ruleset_index = i
            break

    # Create a new ruleset if one doesn't exist for this branch
    if branch_ruleset is None:
        branch_ruleset = {
            "name": f"{branch_name}-protection",
            "target": "branch",
            "enforcement": "active",
            "conditions": {"ref_name": {"include": [f"refs/heads/{branch_name}"], "exclude": []}},
            "rules": [],
        }
        ruleset_index = len(config["rulesets"])
        config["rulesets"].append(branch_ruleset)

    # Apply pre-defined ruleset types
    branch_rule_type = issue_data.get("branch_rule_type")
    if branch_rule_type:
        if branch_rule_type == "standard-protection":
            branch_ruleset["rules"] = [
                {
                    "type": "pull_request",
                    "parameters": {
                        "dismiss_stale_reviews_on_push": True,
                        "require_code_owner_review": False,
                        "required_approving_review_count": 1,
                        "required_review_thread_resolution": True,
                    },
                },
                {"type": "required_linear_history"},
            ]
        elif branch_rule_type == "strict-protection":
            branch_ruleset["rules"] = [
                {
                    "type": "pull_request",
                    "parameters": {
                        "dismiss_stale_reviews_on_push": True,
                        "require_code_owner_review": True,
                        "require_last_push_approval": True,
                        "required_approving_review_count": 2,
                        "required_review_thread_resolution": True,
                    },
                },
                {"type": "required_signatures"},
                {"type": "required_linear_history"},
                {"type": "deletion"},
            ]

    # Update rules with specific settings from the issue
    rules = branch_ruleset.get("rules", [])

    # Handle pull request approvals
    if (
        "require_approvals" in issue_data
        or "require_code_owner_review" in issue_data
        or "dismiss_stale_reviews" in issue_data
    ):
        pr_rule = next((rule for rule in rules if rule.get("type") == "pull_request"), None)

        if pr_rule is None:
            pr_rule = {"type": "pull_request", "parameters": {}}
            rules.append(pr_rule)

        if "parameters" not in pr_rule:
            pr_rule["parameters"] = {}

        if "require_approvals" in issue_data:
            try:
                pr_rule["parameters"]["required_approving_review_count"] = int(issue_data["require_approvals"])
            except (ValueError, TypeError):
                pass

        if "require_code_owner_review" in issue_data:
            pr_rule["parameters"]["require_code_owner_review"] = issue_data["require_code_owner_review"]

        if "dismiss_stale_reviews" in issue_data:
            pr_rule["parameters"]["dismiss_stale_reviews_on_push"] = issue_data["dismiss_stale_reviews"]

    # Handle required status checks
    if issue_data.get("require_status_checks") and issue_data.get("required_status_check_list"):
        status_rule = next((rule for rule in rules if rule.get("type") == "required_status_checks"), None)

        if status_rule is None:
            status_rule = {
                "type": "required_status_checks",
                "parameters": {"strict_required_status_checks_policy": True, "required_status_checks": []},
            }
            rules.append(status_rule)

        if "parameters" not in status_rule:
            status_rule["parameters"] = {}

        if "required_status_checks" not in status_rule["parameters"]:
            status_rule["parameters"]["required_status_checks"] = []

        # Clear existing checks
        status_rule["parameters"]["required_status_checks"] = []

        # Add checks from the issue
        for check in issue_data.get("required_status_check_list", []):
            status_rule["parameters"]["required_status_checks"].append({"context": check})

    # Add/remove other rules based on flags
    if issue_data.get("restrict_push_access") == True:
        if not any(rule.get("type") == "required_signatures" for rule in rules):
            rules.append({"type": "required_signatures"})
    elif issue_data.get("restrict_push_access") == False:
        rules = [rule for rule in rules if rule.get("type") != "required_signatures"]

    # Update the rules in the configuration
    branch_ruleset["rules"] = rules
    config["rulesets"][ruleset_index] = branch_ruleset


def update_config_from_issue_data(config: Dict[str, Any], issue_data: Dict[str, Any]) -> None:
    """Update configuration with issue data."""
    # Map issue fields to configuration fields
    field_mapping = {
        "visibility": "visibility",
        "has_issues": "has_issues",
        "has_projects": "has_projects",
        "has_wiki": "has_wiki",
        "allow_squash_merge": "allow_squash_merge",
        "allow_merge_commit": "allow_merge_commit",
        "allow_rebase_merge": "allow_rebase_merge",
        "allow_auto_merge": "allow_auto_merge",
        "delete_branch_on_merge": "delete_branch_on_merge",
        "allow_update_branch": "allow_update_branch",
    }

    # Update basic settings - only if provided in issue_data
    for issue_field, config_field in field_mapping.items():
        if issue_field in issue_data and issue_data[issue_field] is not None:
            config[config_field] = issue_data[issue_field]

    # Update topics
    if "topics" in issue_data and issue_data["topics"]:
        config["topics"] = issue_data["topics"]

    # Update security settings
    if "enable_vulnerability_alerts" in issue_data or "enable_automated_security_fixes" in issue_data:
        if "security" not in config:
            config["security"] = {}

        if "enable_vulnerability_alerts" in issue_data:
            config["security"]["enableVulnerabilityAlerts"] = issue_data["enable_vulnerability_alerts"]

        if "enable_automated_security_fixes" in issue_data:
            config["security"]["enableAutomatedSecurityFixes"] = issue_data["enable_automated_security_fixes"]

    # Check if we need to update branch rules
    if "branch_name" in issue_data and issue_data.get("branch_name"):
        update_branch_rules(config, issue_data)


def save_repository_config(repo_name: str, config: Dict[str, Any]) -> bool:
    """Save repository configuration to file."""
    repo_dir = f"repositories/{repo_name}"
    repo_file = f"{repo_dir}/repository.yml"

    try:
        # Ensure the directory exists
        os.makedirs(repo_dir, exist_ok=True)

        # Write configuration to file
        with open(repo_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f, sort_keys=False, Dumper=IndentDumper, default_flow_style=False)

        logger.info(f"Successfully saved repository configuration to: {repo_file}")
        return True
    except Exception as e:
        logger.error(f"Error saving repository configuration: {str(e)}")
        return False


def comment_on_issue(repo: str, issue_number: int, message: str, token: str) -> bool:
    """Add a comment to the issue."""
    logger.info(f"Commenting on issue #{issue_number}")
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    data = {"body": message}

    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 201:
            logger.info("Successfully added comment to issue")
            return True

        logger.error(f"Failed to comment on issue: {response.status_code} - {response.text}")
        return False
    except Exception as e:
        logger.error(f"Exception when commenting on issue: {str(e)}")
        return False


def validate_repository_name(name: str) -> bool:
    """Validate repository name format."""
    # Repository names must be lowercase and can only contain letters, numbers, hyphens, and underscores
    pattern = r"^[a-z0-9][a-z0-9-_]*$"
    return bool(re.match(pattern, name))


def validate_required_data(issue_data: Dict[str, Any]) -> list:
    """Validate that the issue data contains required fields."""
    errors = []

    if not issue_data.get("action"):
        errors.append("Missing required field: action")
    elif issue_data["action"] not in ["create", "update", "manage-branch-rules"]:
        errors.append(f"Invalid action: {issue_data['action']}. Must be 'create', 'update', or 'manage-branch-rules'.")

    if not issue_data.get("repository_name"):
        errors.append("Missing required field: repository name")
    elif not validate_repository_name(issue_data["repository_name"]):
        errors.append(
            f"Invalid repository name: {issue_data['repository_name']}. Must be lowercase and contain only letters, numbers, hyphens, and underscores."
        )

    # For manage-branch-rules action, validate branch name
    if issue_data.get("action") == "manage-branch-rules" and not issue_data.get("branch_name"):
        errors.append("Branch name is required when managing branch rules")

    return errors


def get_environment_variables() -> Tuple[int, Dict[str, Any], str, str]:
    """Get and validate environment variables needed for processing."""
    try:
        issue_number = int(os.environ.get("ISSUE_NUMBER"))
        issue_body = os.environ.get("ISSUE_BODY")
        repo = os.environ.get("REPO")
        token = os.environ.get("GITHUB_TOKEN")

        if not issue_body:
            raise ValueError("Issue body is empty")

        # Parse JSON string
        issue_body = json.loads(issue_body)

        missing = []
        if not issue_number:
            missing.append("ISSUE_NUMBER")
        if not issue_body:
            missing.append("ISSUE_BODY")
        if not repo:
            missing.append("REPO")
        if not token:
            missing.append("GITHUB_TOKEN")

        if missing:
            logger.error(f"Missing required environment variables: {', '.join(missing)}")
            sys.exit(1)

        return issue_number, issue_body, repo, token
    except (ValueError, json.JSONDecodeError, TypeError) as e:
        logger.error(f"Error parsing environment variables: {str(e)}")
        sys.exit(1)


def process_repository_issue() -> None:
    """Main function to process repository management issues."""
    logger.info("Starting repository issue processing")

    try:
        # Get environment variables
        issue_number, issue_body, repo, token = get_environment_variables()
        logger.info(f"Processing issue #{issue_number} in repo {repo}")

        # Parse and validate issue data
        issue_data = parse_issue_body(issue_body)
        validation_errors = validate_required_data(issue_data)
        if validation_errors:
            error_message = "⚠️ Validation errors in issue:\n" + "\n".join([f"- {error}" for error in validation_errors])
            logger.error(error_message)
            comment_on_issue(repo, issue_number, error_message, token)
            sys.exit(1)

        # Ensure repositories directory exists
        Path("repositories").mkdir(exist_ok=True)

        repo_name = issue_data["repository_name"]
        action = issue_data["action"]

        # Execute the requested action
        config = None
        error_message = None
        response_message = None

        try:
            if action == "create":
                config, error_message = create_repository_config(repo_name, issue_data)
                if config:
                    response_message = f"✅ Repository configuration for {repo_name} created successfully."
            elif action == "update":
                config, error_message = update_repository_config(repo_name, issue_data)
                if config:
                    response_message = f"✅ Repository configuration for {repo_name} updated successfully."
            elif action == "manage-branch-rules":
                config, error_message = manage_branch_rules(repo_name, issue_data)
                if config:
                    branch_name = issue_data.get("branch_name", "specified branch")
                    response_message = (
                        f"✅ Branch protection rules for {branch_name} in repository {repo_name} updated successfully."
                    )
            else:
                error_message = f"⚠️ Unknown action: {action}. Use 'create', 'update', or 'manage-branch-rules'."
        except Exception as e:
            error_message = f"❌ Error processing repository issue: {str(e)}"
            logger.error(error_message, exc_info=True)

        # Save config if available and no errors
        if config and not error_message:
            if save_repository_config(repo_name, config):
                logger.info(f"Successfully saved repository configuration for {repo_name}")
            else:
                error_message = "❌ Error saving repository configuration"

        # Comment on the issue
        message = error_message if error_message else response_message
        if message:
            comment_on_issue(repo, issue_number, message, token)

        if error_message:
            sys.exit(1)

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    process_repository_issue()
