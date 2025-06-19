#!/usr/bin/env python3

import os
import logging
import re
from collections import OrderedDict
from typing import Dict, Any, Optional
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
        "archived",
        "has_pages",
        "require_code_owner_review",
        "dismiss_stale_reviews",
        "require_status_checks",
        "restrict_push_access",
        "do_not_enforce_on_create",
    ]
    return key in boolean_settings


def to_boolean(value: Any) -> Optional[bool]:
    """Convert various representations to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() == "true":
        return True
    if isinstance(value, str) and value.lower() == "false":
        return False
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
        return to_boolean(issue_data[key])
    # For updates with existing config, don't change if not specified
    if existing_config is not None:
        return None  # Return None to indicate "don't change"
    # For creates without an explicit value, use the default
    return default_config.get(key)


def validate_custom_properties(custom_properties: Dict[str, Any]) -> bool:
    """Validate custom properties against their patterns."""
    for property_name, property_config in custom_properties.items():
        value = property_config.get("value", "")
        pattern = property_config.get("pattern")
        required = property_config.get("required", False)

        # Check if required property has a value
        if required and not value:
            logger.error(f"Required custom property '{property_name}' is missing a value")
            return False

        # Validate pattern if both value and pattern exist
        if pattern and value:
            if not re.match(pattern, value):
                logger.error(f"Custom property '{property_name}' value '{value}' does not match pattern '{pattern}'")
                return False

    return True


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
    """Create or update the repository configuration file."""
    try:
        base_dir = os.environ.get("REPOSITORY_CONFIG_DIR", os.path.join(os.getcwd(), "repositories"))
        repo_dir = os.path.join(base_dir, repo_name)
        os.makedirs(repo_dir, exist_ok=True)

        config_file = os.path.join(repo_dir, "repository.yml")

        # Sort keys in a predictable order for better readability
        ordered_config = OrderedDict()

        # Add core properties first
        core_props = ["name", "description", "visibility", "template", "branch_strategy", "topics"]
        for prop in core_props:
            if prop in repo_config:
                ordered_config[prop] = repo_config[prop]

        # Add custom properties
        if "custom_properties" in repo_config:
            ordered_config["custom_properties"] = repo_config["custom_properties"]

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
            "archived",
            "has_pages",
        ]

        for prop in bool_settings:
            if prop in repo_config:
                ordered_config[prop] = repo_config[prop]

        # Add other settings
        other_settings = ["default_branch"]
        for prop in other_settings:
            if prop in repo_config:
                ordered_config[prop] = repo_config[prop]
                logger.info(f"Adding {prop} to config: {repo_config[prop]}")

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
    """Get existing repository configuration."""
    try:
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
    pattern = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    return bool(re.match(pattern, repo_name))


def update_basic_settings(config: Dict[str, Any], issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update basic repository settings."""
    if "visibility" in issue_data:
        config["visibility"] = issue_data["visibility"]
        logger.info(f"Setting visibility to {issue_data['visibility']}")

    if "description" in issue_data:
        config["description"] = issue_data["description"]
        logger.info(f"Setting description to '{issue_data['description']}'")

    if "branch_strategy" in issue_data:
        branch_strategy = issue_data["branch_strategy"]
        if "(" in branch_strategy:
            branch_strategy = branch_strategy.split("(")[0].strip()
        config["branch_strategy"] = branch_strategy
        logger.info(f"Setting branch strategy to {branch_strategy}")

    if "topics" in issue_data and issue_data["topics"]:
        if "topics" not in config:
            config["topics"] = []
        existing_topics = set(config["topics"])
        for topic in issue_data["topics"]:
            if topic not in existing_topics:
                config["topics"].append(topic)
                logger.info(f"Adding topic: {topic}")

    # Handle custom properties - ensure cost-centre is updated
    if "cost_centre" in issue_data and issue_data["cost_centre"]:
        if "custom_properties" not in config:
            config["custom_properties"] = {}

        if "cost-centre" not in config["custom_properties"]:
            config["custom_properties"]["cost-centre"] = {
                "required": True,
                "pattern": "\\b\\d{6}\\b",
                "description": "Cost centre code (exactly 6 digits)",
            }

        config["custom_properties"]["cost-centre"]["value"] = issue_data["cost_centre"]
        logger.info(f"Setting cost-centre to: {issue_data['cost_centre']}")

    # Explicitly handle default branch setting
    if "default_branch" in issue_data and issue_data["default_branch"]:
        config["default_branch"] = issue_data["default_branch"]
        logger.info(f"Setting default branch to: {issue_data['default_branch']}")

    return config


def update_boolean_settings(config: Dict[str, Any], issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update boolean repository settings."""
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
        "archived",
        "has_pages",
    ]

    for setting in bool_settings:
        if setting in issue_data:
            bool_value = to_boolean(issue_data[setting])
            if bool_value is not None:
                config[setting] = bool_value
                logger.info(f"Setting {setting} to {bool_value}")

    return config


def update_security_settings(config: Dict[str, Any], issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update security settings for repository."""
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
    ruleset_errors = []

    if "ruleset_results" in results:
        for result in results["ruleset_results"]:
            if not result.get("success", True):
                ruleset_errors.append(
                    f"{result.get('name', 'Unnamed ruleset')}: {result.get('message', 'Unknown error')}"
                )

    general_errors = results.get("errors", [])

    if ruleset_errors or general_errors:
        return {"ruleset_errors": ruleset_errors, "general_errors": general_errors}

    return {}
