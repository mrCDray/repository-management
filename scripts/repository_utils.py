#!/usr/bin/env python3

import os
import logging
from collections import OrderedDict
from typing import Dict, Any, Optional
import re
import yaml

# Configure logging
logger = logging.getLogger("repository_processor")


# Configure YAML for better output formatting
class IndentDumper(yaml.Dumper):
    """Custom YAML dumper that maintains indentation"""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


# Setup YAML representers
yaml.add_representer(
    list, lambda dumper, data: dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=False)
)
yaml.add_representer(OrderedDict, lambda dumper, data: dumper.represent_mapping("tag:yaml.org,2002:map", data.items()))


def is_boolean_setting(key: str) -> bool:
    """Check if a setting is expected to be a boolean."""
    boolean_settings = [
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
        "enable_vulnerability_alerts",
        "enable_automated_security_fixes",
        "require_code_owner_review",
        "dismiss_stale_reviews",
        "require_status_checks",
        "restrict_push_access",
    ]
    return key in boolean_settings


def is_boolean_value(value: Any) -> bool:
    """Check if a value is a boolean or a string representation of a boolean."""
    if isinstance(value, bool):
        return True
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return True
    return False


def to_boolean(value: Any) -> Optional[bool]:
    """Convert various representations to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() == "true":
        return True
    if isinstance(value, str) and value.lower() == "false":
        return False
    # Default to None for non-boolean values
    return None


def get_boolean_setting(
    issue_data: Dict[str, Any], key: str, default_config: Dict[str, Any], existing_config: Dict[str, Any] = None
) -> Optional[bool]:
    """Get a boolean setting with proper handling of defaults based on operation type.

    Args:
        issue_data: Data from the issue form
        key: The setting key to check
        default_config: Default configuration to use for create operations
        existing_config: Existing configuration to preserve for update operations

    Returns:
        Boolean value or None if it should be left unchanged
    """
    # If the key is explicitly in issue data, use that value
    if key in issue_data:
        return issue_data[key]
    # For updates with existing config, don't change if not specified
    if existing_config is not None:
        return None  # Return None to indicate "don't change"
    # For creates without an explicit value, use the default
    return default_config.get(key)


def load_default_config() -> Dict[str, Any]:
    """Load default repository configuration."""
    try:
        default_config_path = os.path.join(
            os.environ.get("GITHUB_WORKSPACE", os.getcwd()), "default_repository_config.yml"
        )
        with open(default_config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        logger.info("Loaded default repository configuration")
        return config
    except Exception as e:
        logger.error(f"Failed to load default repository config: {e}")
        return {"repository": {}}


def create_repository_config(repo_name: str, repo_config: Dict[str, Any]) -> bool:
    """Create or update the repository configuration file.

    Args:
        repo_name: Name of the repository
        repo_config: Repository configuration dictionary

    Returns:
        Boolean indicating whether the operation succeeded
    """
    try:
        # Use the proper directory structure: repositories/[repo_name]/repository.yml
        base_dir = os.environ.get("REPOSITORY_CONFIG_DIR", os.path.join(os.getcwd(), "repositories"))
        repo_dir = os.path.join(base_dir, repo_name)
        os.makedirs(repo_dir, exist_ok=True)

        # Create the file path with standard name repository.yml
        config_file = os.path.join(repo_dir, "repository.yml")

        # Sort keys in a predictable order for better readability
        ordered_config = OrderedDict()

        # Add core properties first in a specific order
        core_props = ["name", "description", "visibility", "template", "branch_strategy", "topics"]
        for prop in core_props:
            if prop in repo_config:
                ordered_config[prop] = repo_config[prop]

        # Ensure branch_strategy is always included
        if "branch_strategy" not in ordered_config and "branch_strategy" in repo_config:
            ordered_config["branch_strategy"] = repo_config["branch_strategy"]
        elif "branch_strategy" not in ordered_config:
            ordered_config["branch_strategy"] = "default"
            logger.info(f"Adding default branch strategy to repository config file")

        # Add boolean settings
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

        for prop in bool_settings:
            if prop in repo_config:
                ordered_config[prop] = repo_config[prop]

        # Add security settings
        if "security" in repo_config:
            ordered_config["security"] = repo_config["security"]

        # Add rulesets last
        if "rulesets" in repo_config:
            ordered_config["rulesets"] = repo_config["rulesets"]

        # Write the config as YAML
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(ordered_config, f, Dumper=IndentDumper, default_flow_style=False, sort_keys=False)

        logger.info(f"Created/updated repository config file: {config_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to create repository config file: {e}")
        return False


def get_existing_config(repo_name: str) -> Optional[Dict[str, Any]]:
    """Get existing repository configuration.

    Args:
        repo_name: Name of the repository

    Returns:
        Existing repository configuration or None if not found
    """
    try:
        # Use the proper directory structure: repositories/[repo_name]/repository.yml
        base_dir = os.environ.get("REPOSITORY_CONFIG_DIR", os.path.join(os.getcwd(), "repositories"))
        config_file = os.path.join(base_dir, repo_name, "repository.yml")

        if not os.path.exists(config_file):
            logger.info(f"No existing configuration found for {repo_name}")
            return None

        with open(config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        logger.info(f"Loaded existing configuration for {repo_name}")
        return config
    except Exception as e:
        logger.error(f"Error loading existing configuration: {e}")
        return None


def validate_repository_name(repo_name: str) -> bool:
    """Validate repository name format."""
    # Repository names must be lowercase, contain hyphens instead of spaces,
    # and match GitHub's repository naming rules
    pattern = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    return bool(re.match(pattern, repo_name))


def update_basic_settings(config: Dict[str, Any], issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update basic repository settings."""
    # Handle key settings that should be explicitly overriden if in issue data
    if "visibility" in issue_data:
        config["visibility"] = issue_data["visibility"]
        logger.info(f"Setting visibility to {issue_data['visibility']}")

    # Improved description handling - update if present in issue_data, even if empty
    if "description" in issue_data:
        action = issue_data.get("action", "")
        if action in ("create", "update"):
            config["description"] = issue_data["description"]
            logger.info(f"Setting description to '{issue_data['description']}'")
        else:
            logger.info(f"Ignoring description for action '{action}'")

    # Handle branch strategy if specified (extract the value before any parentheses)
    if "branch_strategy" in issue_data:
        branch_strategy = issue_data["branch_strategy"]
        # Extract the strategy name if it contains parentheses (e.g., "default (Git Flow)")
        if "(" in branch_strategy:
            branch_strategy = branch_strategy.split("(")[0].strip()
        config["branch_strategy"] = branch_strategy
        logger.info(f"Setting branch strategy to {branch_strategy}")

    # Handle topics - add new topics, don't replace existing ones
    if "topics" in issue_data and issue_data["topics"]:
        if "topics" not in config:
            config["topics"] = []
        # Add new topics that don't already exist
        existing_topics = set(config["topics"])
        for topic in issue_data["topics"]:
            if topic not in existing_topics:
                config["topics"].append(topic)
                logger.info(f"Adding topic: {topic}")

    # Log the keys available in issue_data for debugging
    logger.info(f"Issue data keys: {list(issue_data.keys())}")

    return config


def update_boolean_settings(config: Dict[str, Any], issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update boolean repository settings."""
    # Handle all boolean settings - more flexibly handle boolean values
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
        # Check if setting is in issue_data and can be interpreted as a boolean
        if setting in issue_data:
            bool_value = to_boolean(issue_data[setting])
            if bool_value is not None:  # Only update if we got a valid boolean
                config[setting] = bool_value
                logger.info(f"Setting {setting} to {bool_value}")
            else:
                logger.warning(f"Ignoring non-boolean value for {setting}: {issue_data[setting]}")

    return config


def update_security_settings(config: Dict[str, Any], issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update security settings for repository."""
    # Handle security settings if present in issue data
    if "security" in issue_data:
        if "security" not in config:
            config["security"] = {}

        for key, value in issue_data["security"].items():
            bool_value = to_boolean(value)
            if bool_value is not None:
                config["security"][key] = bool_value
                logger.info(f"Setting security.{key} to {bool_value}")

    return config


def process_sync_results(results: Dict[str, Any]) -> Dict[str, Any]:
    """Process sync results to create a user-friendly response"""
    # Extract ruleset results if available
    ruleset_errors = []

    if "ruleset_results" in results:
        for result in results["ruleset_results"]:
            if not result.get("success", True):
                ruleset_errors.append(
                    f"{result.get('name', 'Unnamed ruleset')}: {result.get('message', 'Unknown error')}"
                )

    # Extract general errors
    general_errors = results.get("errors", [])

    if ruleset_errors or general_errors:
        return {"ruleset_errors": ruleset_errors, "general_errors": general_errors}

    return {}
