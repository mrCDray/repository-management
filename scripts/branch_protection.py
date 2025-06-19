#!/usr/bin/env python3

import os
import json
import logging
import sys
from typing import Dict, Any, List
import yaml
from sync_github_repositories import GitHubRepositoryManager

# Import utilities from the new modules
from repository_utils import (
    load_default_config,
    create_repository_config,
    get_existing_config,
    update_basic_settings,
    update_boolean_settings,
    update_security_settings,
    validate_repository_name,
    process_sync_results,
    get_boolean_setting,
    to_boolean,
)

from branch_protection import (
    create_branch_protection_ruleset,
    parse_list_section,
    select_branch_strategy_ruleset,
    update_rulesets,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("repository_processor")


def process_section(section_name: str, content: List[str]) -> Any:
    """Process a single section from the issue body and return its value."""
    if not content:
        return None

    section_value = "\n".join(content).strip()
    if not section_value:
        return None

    # Skip "_No response_" values which indicate no changes requested
    if section_value == "_No response_":
        logger.info(f"Ignoring '{section_name}' with value '_No response_'")
        return None

    # Handle different field types
    if section_name in ("topics", "required_status_check_list", "branch_includes", "branch_excludes"):
        return parse_list_section(section_value)

    # Convert true/false strings to booleans only if exact match
    if section_value.lower() == "true":
        return True
    if section_value.lower() == "false":
        return False
    if section_value.lower() in ("none", ""):
        return None

    # Handle special case for rulesets in JSON format
    if section_name == "rulesets" and section_value.startswith("[") and section_value.endswith("]"):
        try:
            return json.loads(section_value)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse rulesets JSON: {section_value}")
            # Try to recover by treating as a YAML list
            try:
                return yaml.safe_load(section_value)
            except Exception:
                logger.error(f"Also failed to parse as YAML: {section_value}")

    return section_value


def parse_issue_body(body: str) -> Dict[str, Any]:
    """Parse the issue body to extract input values."""
    logger.info("Parsing issue body")

    # Handle escaped quotes in JSON string (common when using toJSON in GitHub Actions)
    if body.startswith('"') and body.endswith('"'):
        try:
            body = json.loads(body)
            logger.info("Successfully unescaped JSON body")
        except json.JSONDecodeError:
            logger.warning("Failed to unescape JSON body, using raw string")

    lines = body.split("\n")
    logger.debug(f"Issue body has {len(lines)} lines")

    result = {}
    current_section = None
    current_content = []

    for line in lines:
        line = line.rstrip()

        # GitHub issue forms use ### for field labels
        if line.startswith("### "):
            # Save previous section if any
            if current_section and current_content:
                processed_value = process_section(current_section, current_content)
                if processed_value is not None:
                    result[current_section] = processed_value

            # Start new section
            current_section = line[4:].lower().replace(" ", "_")
            current_content = []
        elif current_section:
            # Add line to current section content if not empty
            if line.strip():
                current_content.append(line)

    # Process final section
    if current_section and current_content:
        processed_value = process_section(current_section, current_content)
        if processed_value is not None:
            result[current_section] = processed_value

    # If topics or required_status_check_list is empty, remove it
    for key in ["topics", "required_status_check_list", "branch_includes", "branch_excludes"]:
        if key in result and not result[key]:
            del result[key]

    # Log all sections found in the issue body for debugging
    logger.info(f"Sections found in issue body: {list(result.keys())}")

    # Special logging for description field to verify its presence and value
    if "description" in result:
        logger.info(f"Found description field with value: '{result['description']}'")
    elif "repository_description" in result:
        logger.info(f"Found repository_description field with value: '{result['repository_description']}'")
    else:
        logger.warning("No description or repository_description field found in issue body")

    # Special handling for boolean fields
    if "do_not_require_status_checks_on_creation" in result:
        result["do_not_require_status_checks_on_creation"] = to_boolean(
            result["do_not_require_status_checks_on_creation"]
        )

    # Special handling for branch protection rules section
    if "branch_name" in result and "branch_rule_type" in result:
        branch_name = result.get("branch_name")
        branch_rule_type = result.get("branch_rule_type")
        branch_includes = result.get("branch_includes", [])
        branch_excludes = result.get("branch_excludes", [])

        if branch_name and branch_rule_type and (branch_includes or branch_excludes):
            # Create a ruleset based on the branch protection information
            ruleset = create_branch_protection_ruleset(
                branch_name, branch_rule_type, branch_includes, branch_excludes, result
            )

            # Add to rulesets or create the rulesets array
            if "rulesets" not in result:
                result["rulesets"] = []
            result["rulesets"].append(ruleset)

            logger.info(f"Created branch protection ruleset: {ruleset['name']}")

    # Apply field mappings
    apply_field_mappings(result)

    logger.info(f"Parsed issue data: {json.dumps(result, default=str)}")
    return result


def apply_field_mappings(result: Dict[str, Any]) -> None:
    """Apply field mappings and transformations to the parsed data."""
    # Map form fields to expected fields if needed
    field_mapping = {
        "require_approvals": "required_approving_review_count",
        "repository_visibility": "visibility",
        "template_repository": "template",
        "repository_description": "description",  # Add mapping for repository_description
        "enable_vulnerability_alerts": "_security_vulnerability_alerts",
        "enable_automated_security_fixes": "_security_automated_fixes",
        "branch_protection_rule_name": "branch_name",
        "require_pull_request_approvals": "require_approvals",
        "allow_initial_branch_creation_without_status_checks": "do_not_require_status_checks_on_creation",
    }

    for old_key, new_key in field_mapping.items():
        if old_key in result and new_key not in result:
            result[new_key] = result[old_key]
            # Keep the original key for reference
            if not old_key.startswith("_"):  # Don't remove special mapping keys
                del result[old_key]

    # Handle security settings conversions
    security_keys = {
        "_security_vulnerability_alerts": "enableVulnerabilityAlerts",
        "_security_automated_fixes": "enableAutomatedSecurityFixes",
    }
    has_security_settings = any(k in result for k in security_keys)
    if has_security_settings:
        result["security"] = {}
        for result_key, config_key in security_keys.items():
            if result_key in result:
                result["security"][config_key] = result[result_key]
                del result[result_key]


def process_repository_issue(issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process repository management issue data and perform requested actions."""
    action = issue_data.get("action")
    repo_name = issue_data.get("repository_name")

    if not repo_name:
        return {"status": "error", "message": "Repository name is required"}

    # Validate repository name format
    if not validate_repository_name(repo_name):
        return {"status": "error", "message": "Invalid repository name format"}

    # Get GitHub token and organization
    github_token = os.environ.get("GITHUB_TOKEN")
    github_org = os.environ.get("GITHUB_ORG")

    if not github_token or not github_org:
        return {"status": "error", "message": "Missing GitHub token or organization name"}

    # Initialize the GitHub repository manager
    try:
        repo_manager = GitHubRepositoryManager(github_token, github_org)
        logger.info(f"Initialized GitHub repo manager for {github_org}")
    except Exception as e:
        logger.error(f"Failed to initialize GitHub repository manager: {e}")
        return {"status": "error", "message": f"Failed to initialize GitHub API: {str(e)}"}

    # Call appropriate function based on action
    if action == "create":
        return create_repository(repo_manager, repo_name, issue_data)
    if action == "update":
        return update_repository(repo_manager, repo_name, issue_data)
    if action == "remove":
        return remove_repository(repo_manager, repo_name, issue_data)

    return {"status": "error", "message": "Invalid action specified"}


def create_repository(
    repo_manager: GitHubRepositoryManager, repo_name: str, issue_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle repository creation."""
    try:
        # First check if repository already exists
        if repo_manager.repo_exists(repo_name):
            return {"status": "error", "message": f"Repository {repo_name} already exists"}

        # Load and prepare configuration
        repo_config = _prepare_repository_config(repo_name, issue_data)

        # Create repository configuration file
        if not create_repository_config(repo_name, repo_config):
            return {"status": "error", "message": "Failed to create repository configuration file"}

        # Create the repository using GitHub API
        logger.info(f"Creating GitHub repository: {repo_name}")
        repo = repo_manager.create_repository(repo_config)

        if not repo:
            return {"status": "error", "message": "Failed to create GitHub repository"}

        # Create default branches based on branch strategy
        branch_strategy = repo_config.get("branch_strategy", "default")
        branch_result = create_default_branches(repo, branch_strategy)

        # Process any sync results to extract warnings and errors
        sync_results = getattr(repo, "_sync_results", {})
        error_info = process_sync_results(sync_results)

        # Prepare response
        return _prepare_creation_response(repo_name, branch_result, error_info)

    except Exception as e:
        logger.error(f"Error creating repository: {e}", exc_info=True)
        return {"status": "error", "message": f"Failed to create repository: {str(e)}"}


def _prepare_repository_config(repo_name: str, issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare repository configuration from issue data and defaults."""
    # Load default configuration
    default_config = load_default_config().get("repository", {})

    # Replace the placeholder repository name with the actual name
    if default_config.get("name") == "[repository_name]":
        default_config["name"] = repo_name

    # Create a clean config starting with core properties
    repo_config = {
        "name": repo_name,
        "visibility": issue_data.get("visibility", default_config.get("visibility", "private")),
    }

    # Improved description handling - always include description even if empty
    if "description" in issue_data:
        repo_config["description"] = issue_data["description"]
        logger.info(f"Setting description to: '{issue_data['description']}'")
    elif "description" in default_config:
        repo_config["description"] = default_config["description"]

    # Add template if specified
    if "template" in issue_data and issue_data["template"]:
        repo_config["template"] = issue_data["template"]
    elif "template" in default_config:
        repo_config["template"] = default_config["template"]

    # Add default branch if specified
    if "default_branch" in issue_data and issue_data["default_branch"]:
        repo_config["default_branch"] = issue_data["default_branch"]
        logger.info(f"Setting default branch to: {issue_data['default_branch']}")
    elif "default_branch" in default_config:
        repo_config["default_branch"] = default_config["default_branch"]
        logger.info(f"Using default branch from default config: {default_config['default_branch']}")

    # Handle cost-centre custom property
    if "cost_centre" in issue_data and issue_data["cost_centre"]:
        if "custom_properties" not in repo_config:
            repo_config["custom_properties"] = {}
        repo_config["custom_properties"]["cost-centre"] = {
            "value": issue_data["cost_centre"],
            "required": True,
            "pattern": "\\b\\d{6}\\b",
            "description": "Cost centre code (exactly 6 digits)",
        }
        logger.info(f"Setting cost-centre to: {issue_data['cost_centre']}")
    elif "custom_properties" in default_config:
        repo_config["custom_properties"] = default_config["custom_properties"]

    # Add boolean settings
    _add_boolean_settings(repo_config, issue_data, default_config)

    # Handle topics
    _add_topics(repo_config, issue_data, default_config)

    # Handle security settings
    _add_security_settings(repo_config, issue_data, default_config)

    # Apply branch strategy ruleset selection - always default to git-flow if not specified
    branch_strategy = issue_data.get("branch_strategy", "git-flow")
    if branch_strategy == "_No response_" or not branch_strategy:
        branch_strategy = "git-flow"
        logger.info(f"Using git-flow as default branch strategy")

    # Ensure strategy is properly formatted (remove parenthetical notes)
    if isinstance(branch_strategy, str) and "(" in branch_strategy:
        branch_strategy = branch_strategy.split("(")[0].strip()

    repo_config["branch_strategy"] = branch_strategy
    logger.info(f"Setting branch strategy to: {branch_strategy}")

    # Select and apply branch strategy ruleset
    repo_config = select_branch_strategy_ruleset(repo_config, issue_data, default_config)

    # Handle custom rulesets only if branch strategy is "custom"
    if isinstance(branch_strategy, str) and branch_strategy.startswith("custom"):
        custom_rulesets = issue_data.get("rulesets", [])
        if custom_rulesets:
            logger.info(f"Applying {len(custom_rulesets)} custom rulesets")
            repo_config["rulesets"] = custom_rulesets

    return repo_config


def _add_boolean_settings(
    repo_config: Dict[str, Any], issue_data: Dict[str, Any], default_config: Dict[str, Any]
) -> None:
    """Add boolean settings to repository configuration."""
    bool_settings = [
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

    for setting in bool_settings:
        # Explicitly check if the setting is in issue_data to preserve user selections
        if setting in issue_data:
            value = get_boolean_setting(issue_data, setting, default_config)
            if value is not None:  # Only set if a value is determined
                repo_config[setting] = value
        else:
            # For settings not in issue_data, use default value
            if setting in default_config:
                repo_config[setting] = default_config[setting]


def _add_topics(repo_config: Dict[str, Any], issue_data: Dict[str, Any], default_config: Dict[str, Any]) -> None:
    """Add topics to repository configuration."""
    if "topics" in issue_data and issue_data["topics"]:
        clean_topics = [topic for topic in issue_data["topics"] if topic != "_No response_"]
        if clean_topics:
            repo_config["topics"] = clean_topics
    elif "topics" in default_config:
        repo_config["topics"] = default_config["topics"]


def _add_security_settings(
    repo_config: Dict[str, Any], issue_data: Dict[str, Any], default_config: Dict[str, Any]
) -> None:
    """Add security settings to repository configuration."""
    if "security" in issue_data:
        repo_config["security"] = issue_data["security"]
    elif "security" in default_config:
        repo_config["security"] = default_config["security"]


def _prepare_creation_response(
    repo_name: str, branch_result: Dict[str, Any], error_info: Dict[str, Any]
) -> Dict[str, Any]:
    """Prepare response for repository creation."""
    response = {"status": "success", "message": f"Repository {repo_name} created successfully"}

    # Add branch creation status to response
    if branch_result:
        if branch_result.get("status") == "success":
            response["message"] += f" with {branch_result.get('branches_created', 0)} branches created"
        else:
            response["message"] += f" (but branch creation had issues: {branch_result.get('message', '')})"

    # Add any errors/warnings to the response
    if error_info:
        if "ruleset_errors" in error_info and error_info["ruleset_errors"]:
            response["ruleset_errors"] = error_info["ruleset_errors"]
        if "general_errors" in error_info and error_info["general_errors"]:
            response["message"] += f" (with {len(error_info['general_errors'])} errors)"
            response["general_errors"] = error_info["general_errors"]

    return response


# Fix the unused argument and bare except issues
def create_default_branches(repo, branch_strategy: str) -> Dict[str, Any]:
    """Create default branches based on the selected branch strategy."""
    try:
        branches_to_create = []

        # Determine which branches to create based on branch strategy
        if branch_strategy in ("git-flow", "default"):
            branches_to_create.append({"name": "develop", "source": "main"})
        elif branch_strategy == "gitlab-flow":
            branches_to_create.append({"name": "production", "source": "main"})
            branches_to_create.append({"name": "staging", "source": "main"})
        elif branch_strategy == "release-flow":
            # No additional branches needed by default
            pass
        elif branch_strategy == "trunk-based":
            # Check if main exists, if not create it as 'trunk'
            try:
                repo.get_branch("main")
            except Exception:  # Replace bare except with Exception
                branches_to_create.append({"name": "trunk", "source": "main"})

        # Create the branches using GitHub API
        branches_created = 0
        for branch in branches_to_create:
            try:
                # Get the source branch reference
                source_ref = repo.get_git_ref(f"heads/{branch['source']}")
                if source_ref:
                    # Create new branch from the source branch
                    repo.create_git_ref(ref=f"refs/heads/{branch['name']}", sha=source_ref.object.sha)
                    logger.info(f"Created branch {branch['name']} from {branch['source']}")
                    branches_created += 1
            except Exception as e:  # Specify exception type
                logger.error(f"Error creating branch {branch['name']}: {e}")
                return {
                    "status": "error",
                    "message": f"Error creating branch {branch['name']}: {str(e)}",
                    "branches_created": branches_created,
                }

        return {
            "status": "success",
            "message": f"Created {branches_created} branches",
            "branches_created": branches_created,
        }

    except Exception as e:  # Specify exception type
        logger.error(f"Error creating default branches: {e}")
        return {"status": "error", "message": f"Failed to create default branches: {str(e)}"}


def update_repository(
    repo_manager: GitHubRepositoryManager, repo_name: str, issue_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle repository updates."""
    try:
        # Check if repository exists
        if not repo_manager.repo_exists(repo_name):
            return {"status": "error", "message": f"Repository {repo_name} does not exist"}

        # Get existing repository configuration
        existing_config = get_existing_config(repo_name)
        logger.info(f"Loaded existing config for {repo_name}: {json.dumps(existing_config, default=str)}")

        if not existing_config:
            # If no existing config, create one based on default
            existing_config = load_default_config().get("repository", {}).copy()
            existing_config["name"] = repo_name

        # Prepare updated configuration by merging existing config with issue data
        updated_config = _prepare_update_config(existing_config, issue_data)

        # Handle branch strategy configuration
        updated_config = _handle_branch_strategy(updated_config, issue_data)

        # Handle ruleset configuration
        updated_config = _handle_rulesets(updated_config, issue_data)

        # Log the final configuration that will be applied
        logger.info(f"Final updated configuration: {json.dumps(updated_config, default=str)}")

        # Create/update repository configuration file
        if not create_repository_config(repo_name, updated_config):
            return {"status": "error", "message": "Failed to update repository configuration file"}

        # Update the repository using GitHub API
        logger.info(f"Updating GitHub repository: {repo_name}")
        repo = repo_manager.update_repository(repo_name, updated_config)

        if not repo:
            return {"status": "error", "message": "Failed to update GitHub repository"}

        # Process any sync results to extract warnings and errors
        sync_results = getattr(repo, "_sync_results", {})
        error_info = process_sync_results(sync_results)

        response = {"status": "success", "message": f"Repository {repo_name} updated successfully"}

        # Add any errors/warnings to the response
        if error_info:
            if "ruleset_errors" in error_info and error_info["ruleset_errors"]:
                response["ruleset_errors"] = error_info["ruleset_errors"]
            if "general_errors" in error_info and error_info["general_errors"]:
                response["message"] += f" (with {len(error_info['general_errors'])} errors)"
                response["general_errors"] = error_info["general_errors"]

        logger.info(f"Successfully updated repository {repo_name}")
        return response

    except Exception as e:
        logger.error(f"Error updating repository: {e}", exc_info=True)
        return {"status": "error", "message": f"Failed to update repository: {str(e)}"}


def _prepare_update_config(existing_config: Dict[str, Any], issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare configuration for repository update by merging existing config with issue data."""
    updated_config = existing_config.copy()

    # Explicitly handle default branch if specified
    if "default_branch" in issue_data and issue_data["default_branch"]:
        updated_config["default_branch"] = issue_data["default_branch"]
        logger.info(f"Setting default branch to: {issue_data['default_branch']}")

    # Apply updates to configuration
    updated_config = update_basic_settings(updated_config, issue_data)
    updated_config = update_boolean_settings(updated_config, issue_data)
    updated_config = update_security_settings(updated_config, issue_data)

    # Handle cost-centre custom property update
    if "cost_centre" in issue_data and issue_data["cost_centre"]:
        if "custom_properties" not in updated_config:
            updated_config["custom_properties"] = {}

        # If cost-centre already exists, update it; otherwise create it
        if "cost-centre" not in updated_config["custom_properties"]:
            updated_config["custom_properties"]["cost-centre"] = {
                "required": True,
                "pattern": "\\b\\d{6}\\b",
                "description": "Cost centre code (exactly 6 digits)",
            }

        # Always update the value
        updated_config["custom_properties"]["cost-centre"]["value"] = issue_data["cost_centre"]
        logger.info(f"Updating cost-centre to: {issue_data['cost_centre']}")

    return updated_config


def _handle_branch_strategy(config: Dict[str, Any], issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle branch strategy configuration updates."""
    # Load default config for branch strategies
    default_config = load_default_config().get("repository", {})

    # Handle branch strategy - ensure it's always in the config
    if "branch_strategy" in issue_data and issue_data["branch_strategy"] not in (None, "", "_No response_"):
        branch_strategy = issue_data["branch_strategy"]
        # Clean up format (remove parenthetical info)
        if isinstance(branch_strategy, str) and "(" in branch_strategy:
            branch_strategy = branch_strategy.split("(")[0].strip()

        config["branch_strategy"] = branch_strategy
        logger.info(f"Updating branch strategy to: {branch_strategy}")
        config = select_branch_strategy_ruleset(config, issue_data, default_config)
    elif "branch_strategy" not in config:
        # Default to git-flow if branch_strategy is missing
        config["branch_strategy"] = "git-flow"
        logger.info("Setting git-flow as default branch strategy")
        # Apply git-flow branch strategy ruleset
        config = select_branch_strategy_ruleset(config, {"branch_strategy": "git-flow"}, default_config)

    return config


def _handle_rulesets(config: Dict[str, Any], issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle ruleset configuration updates."""
    branch_strategy = config.get("branch_strategy", "")

    # For update action: Create new rulesets or update existing ones if using custom strategy
    if isinstance(branch_strategy, str) and branch_strategy.startswith("custom"):
        # Check if we need to create a new ruleset based on branch protection fields
        if "branch_name" in issue_data and issue_data["branch_name"] and "branch_rule_type" in issue_data:
            branch_name = issue_data.get("branch_name")
            branch_rule_type = issue_data.get("branch_rule_type")
            branch_includes = issue_data.get("branch_includes", [])
            branch_excludes = issue_data.get("branch_excludes", [])

            if branch_name and branch_rule_type and (branch_includes or branch_excludes):
                # Create ruleset from branch protection
                ruleset = create_branch_protection_ruleset(
                    branch_name, branch_rule_type, branch_includes, branch_excludes, issue_data
                )

                # Add to existing rulesets or create new array
                if "rulesets" not in config:
                    config["rulesets"] = []

                # Check if this ruleset already exists and replace it, or add as new
                existing_idx = next((i for i, r in enumerate(config["rulesets"]) if r.get("name") == branch_name), None)
                if existing_idx is not None:
                    config["rulesets"][existing_idx] = ruleset
                    logger.info(f"Replacing existing ruleset: {branch_name}")
                else:
                    config["rulesets"].append(ruleset)
                    logger.info(f"Adding new ruleset: {branch_name}")
        # Only apply custom rulesets if strategy is "custom"
        config = update_rulesets(config, issue_data)
    elif "branch_name" in issue_data and issue_data["branch_name"]:
        # Allow custom ruleset updates or removals regardless of strategy for update/remove actions
        if issue_data.get("action") in ("update", "remove"):
            config = update_rulesets(config, issue_data)

    return config


def remove_repository(
    repo_manager: GitHubRepositoryManager, repo_name: str, issue_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle repository removal of settings (not deletion)."""
    try:
        # Check if repository exists
        if not repo_manager.repo_exists(repo_name):
            return {"status": "error", "message": f"Repository {repo_name} does not exist"}

        # Get existing repository configuration
        existing_config = get_existing_config(repo_name)

        if not existing_config:
            return {"status": "error", "message": f"Repository configuration not found for {repo_name}"}

        updated_config = existing_config.copy()

        # Handle removals based on what's specified in issue_data
        # Only handle non-boolean settings for removal

        # Remove specified topics
        if "topics" in issue_data and issue_data["topics"]:
            topics_to_remove = set(issue_data["topics"])
            if "topics" in updated_config:
                updated_config["topics"] = [t for t in updated_config["topics"] if t not in topics_to_remove]

        # Remove specified branch protection rule
        if "branch_name" in issue_data and issue_data["branch_name"]:
            branch_rule_name = issue_data["branch_name"]
            if "rulesets" in updated_config:
                # Check if the ruleset exists before removing
                ruleset_exists = any(rule.get("name") == branch_rule_name for rule in updated_config["rulesets"])
                if ruleset_exists:
                    logger.info(f"Removing ruleset: {branch_rule_name}")
                    updated_config["rulesets"] = [
                        rule for rule in updated_config["rulesets"] if rule.get("name") != branch_rule_name
                    ]
                else:
                    logger.warning(f"Ruleset {branch_rule_name} not found, nothing to remove")

        # Create/update repository configuration file
        if not create_repository_config(repo_name, updated_config):
            return {"status": "error", "message": "Failed to update repository configuration file"}

        # Update the repository using GitHub API
        logger.info(f"Applying removals to GitHub repository: {repo_name}")
        repo = repo_manager.update_repository(repo_name, updated_config)

        if not repo:
            return {"status": "error", "message": "Failed to update GitHub repository with removals"}

        logger.info(f"Successfully removed settings from repository {repo_name}")
        return {"status": "success", "message": f"Successfully removed specified settings from repository {repo_name}"}

    except Exception as e:
        logger.error(f"Error removing settings from repository: {e}")
        return {"status": "error", "message": f"Failed to remove settings: {str(e)}"}


if __name__ == "__main__":
    issue_body = os.getenv("ISSUE_BODY")
    if issue_body:
        issue_data = parse_issue_body(issue_body)
        result = process_repository_issue(issue_data)
        print(json.dumps(result))
    else:
        logger.error("ISSUE_BODY environment variable is required")
        sys.exit(1)
