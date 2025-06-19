#!/usr/bin/env python3

import time
import json
import re
from typing import Dict, Any, Optional
import requests
from github import GithubException


def _get_bool_value(config: Dict[str, Any], key: str, default: bool) -> bool:
    """
    Get a boolean value from configuration dictionary, with fallback to default.
    Ensures the return value is always a boolean, never None.
    """
    value = config.get(key)
    if value is None:
        return default
    return bool(value)


def create_repository(github_manager, config: Dict[str, Any]) -> Optional[Any]:
    """Create a new GitHub repository with the specified configuration."""
    logger = github_manager.logger
    org = github_manager.org
    github_token = github_manager.github_token

    repo_name = config.get("name")
    if not repo_name:
        logger.error("Repository name is required")
        return None

    try:
        # Check if repository already exists
        if github_manager.repo_exists(repo_name):
            logger.info(f"Repository {repo_name} already exists, skipping creation")
            return org.get_repo(repo_name)

        # Check if a template repository is specified
        template_repo_name = config.get("template")

        # Ensure we have visibility set - default to private if not specified
        visibility = config.get("visibility", "private").lower()
        logger.info(f"Creating repository with visibility: {visibility}")

        if isinstance(template_repo_name, str) and template_repo_name.lower() != "none":
            logger.info(f"Creating repository {repo_name} from template {template_repo_name}")
            try:
                # Get the template repository to verify it exists
                org.get_repo(template_repo_name)  # Just verify it exists, no need to store

                # Use the GitHub REST API directly to generate repository from template
                api_url = f"https://api.github.com/repos/{org.login}/{template_repo_name}/generate"

                headers = {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {github_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                }

                payload = {
                    "owner": org.login,
                    "name": repo_name,
                    "description": config.get("description", ""),  # Ensure description is included
                    "private": True,  # Always create as private initially
                    "include_all_branches": False,
                }

                # Log the payload for debugging
                logger.info(f"Template creation payload: {json.dumps(payload)}")

                logger.info(f"Making API request to create repository from template: {api_url}")
                response = requests.post(api_url, headers=headers, json=payload)

                if response.status_code in (201, 200):
                    logger.info(f"Successfully created repository {repo_name} from template {template_repo_name}")
                    # Wait briefly for repository to be fully created
                    time.sleep(2)
                    # Get the newly created repository
                    repo = org.get_repo(repo_name)

                    # Make sure visibility is applied properly after template creation
                    if visibility != "private":
                        logger.info(f"Updating repository {repo_name} to {visibility} visibility")
                        repo.edit(visibility=visibility)
                else:
                    logger.error(f"Failed to create repository from template: {response.status_code} - {response.text}")
                    raise GithubException(response.status_code, f"GitHub API returned: {response.text}")

            except Exception as e:
                logger.error(f"Failed to create repository from template: {str(e)}")

                # Fall back to regular creation if template doesn't exist or other issues
                logger.info("Falling back to standard repository creation")
                repo = org.create_repo(
                    name=repo_name, private=(visibility != "public"), visibility=visibility, auto_init=True
                )
        else:
            # Create new repository without template
            repo = org.create_repo(
                name=repo_name,
                description=config.get("description", ""),  # Explicitly pass description
                private=(visibility != "public"),
                visibility=visibility,
                auto_init=True,
            )
            logger.info(
                f"Created new repository {repo_name} with visibility {visibility} and description '{config.get('description', '')}'"
            )

        # Apply settings to the new repository
        github_manager.update_repository_settings(repo, config)

        # Apply custom properties if configured
        if "custom_properties" in config:
            update_custom_properties(
                logger, github_manager.github_token, org.login, repo_name, config["custom_properties"]
            )

        return repo

    except GithubException as e:
        logger.error(f"GitHub API error while creating repository {repo_name}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error creating repository {repo_name}: {e}")
        raise


def update_repository(github_manager, repo_name: str, config: Dict[str, Any]) -> Optional[Any]:
    """Update an existing GitHub repository with new configuration."""
    logger = github_manager.logger
    org = github_manager.org

    try:
        # Get existing repository
        repo = org.get_repo(repo_name)

        # Verify repository name matches config
        if config.get("name") != repo_name:
            raise ValueError(
                f"Repository name in config ({config.get('name')}) does not match expected name ({repo_name})"
            )

        # Explicitly log default branch if it's being changed
        if "default_branch" in config and config["default_branch"] != repo.default_branch:
            logger.info(f"Will update default branch from {repo.default_branch} to {config['default_branch']}")

        # Update repository settings
        github_manager.update_repository_settings(repo, config)

        # Update custom properties if configured
        if "custom_properties" in config:
            update_custom_properties(
                logger, github_manager.github_token, org.login, repo_name, config["custom_properties"]
            )

        return repo

    except GithubException as e:
        logger.error(f"GitHub API error while updating repository {repo_name}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error updating repository {repo_name}: {e}")
        raise


def update_basic_repo_settings(logger, repo, config: Dict[str, Any]) -> bool:
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
        "archived",
        "has_pages",
    ]

    # Check each setting and only include if explicitly defined in config
    for setting in repo_settings:
        if setting in config:
            current_value = getattr(repo, setting, None)
            new_value = config[setting]
            if current_value != new_value:
                logger.info(f"Updating {setting}: {current_value} -> {new_value}")
                update_params[setting] = new_value
                settings_changed = True

    # Handle default branch separately
    if "default_branch" in config and config["default_branch"] != repo.default_branch:
        logger.info(f"Updating default branch: {repo.default_branch} -> {config['default_branch']}")
        update_params["default_branch"] = config["default_branch"]
        settings_changed = True

    # Only call edit if there are parameters to update
    if update_params:
        logger.info(f"Updating repository settings: {update_params}")
        repo.edit(**update_params)

    return settings_changed


def update_repository_metadata(logger, repo, config: Dict[str, Any]) -> bool:
    """Update repository description and visibility."""
    settings_changed = False

    # Debug log to help diagnose description issues
    logger.info(
        f"Description in config: '{config.get('description', '<not set>')}', Current description: '{repo.description}'"
    )

    # Handle description separately as it's a common field to update
    if "description" in config and config["description"] != repo.description:
        # Always update description if it's explicitly set in config, even if empty
        logger.info(f"Updating description: '{repo.description}' -> '{config['description']}'")
        repo.edit(description=config["description"])
        settings_changed = True

    # Handle visibility separately
    if "visibility" in config:
        visibility = config["visibility"].lower()
        if repo.visibility != visibility:
            logger.info(f"Updating visibility: {repo.visibility} -> {visibility}")
            repo.edit(visibility=visibility)
            settings_changed = True

    return settings_changed


def update_security_settings(logger, repo, security_config: Dict[str, Any]) -> bool:
    """Update repository security settings."""
    settings_changed = False

    # Enhanced security settings
    security_settings = {
        "enableVulnerabilityAlerts": ("enable_vulnerability_alert", "disable_vulnerability_alert"),
        "enableAutomatedSecurityFixes": ("enable_automated_security_fixes", "disable_automated_security_fixes"),
    }

    for config_key, (enable_method, disable_method) in security_settings.items():
        if config_key in security_config:
            should_enable = security_config[config_key]
            try:
                if should_enable:
                    logger.info(f"Enabling {config_key}")
                    getattr(repo, enable_method)()
                    settings_changed = True
                else:
                    logger.info(f"Disabling {config_key}")
                    getattr(repo, disable_method)()
                    settings_changed = True
            except Exception as e:
                logger.warning(f"Could not update {config_key}: {e}")

    return settings_changed


def update_topics(logger, repo, topics: list) -> bool:
    """Update repository topics."""
    settings_changed = False
    current_topics = repo.get_topics()

    if set(topics) != set(current_topics):
        logger.info(f"Updating topics: {current_topics} -> {topics}")
        try:
            repo.replace_topics(topics)
            settings_changed = True
        except Exception as e:
            logger.warning(f"Could not set repository topics: {e}")

    return settings_changed


def update_custom_properties(
    logger, github_token: str, org_name: str, repo_name: str, custom_properties: Dict[str, Any]
) -> bool:
    """Update repository custom properties."""
    settings_changed = False

    for property_name, property_config in custom_properties.items():
        try:
            # Set custom property value
            api_url = f"https://api.github.com/repos/{org_name}/{repo_name}/properties/values"

            headers = {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {github_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }

            # Validate pattern if provided
            value = property_config.get("value", "")

            # Skip empty values - this prevents wiping out existing values when not specified
            if not value:
                logger.info(f"Skipping custom property '{property_name}' as value is empty")
                continue

            pattern = property_config.get("pattern")

            # Special handling for cost-centre to ensure it matches GitHub's pattern
            if property_name == "cost-centre":
                # Ensure it's exactly 6 digits
                if not re.match(r"^\d{6}$", value):
                    logger.error(f"Cost centre must be exactly 6 digits, got: '{value}'")
                    continue
                logger.info(f"Updating cost-centre custom property to '{value}'")

            # General pattern validation
            elif pattern and value:
                if not re.match(pattern, value):
                    logger.error(
                        f"Custom property '{property_name}' value '{value}' does not match pattern '{pattern}'"
                    )
                    continue

            payload = {"properties": [{"property_name": property_name, "value": value}]}

            # Log the request payload for debugging
            logger.info(f"Sending custom property update: {property_name}={value}")

            response = requests.patch(api_url, headers=headers, json=payload)

            if response.status_code in (200, 201, 204):
                logger.info(f"Updated custom property '{property_name}' to '{value}'")
                settings_changed = True
            else:
                logger.warning(
                    f"Failed to update custom property '{property_name}': {response.status_code} - {response.text}"
                )

        except Exception as e:
            logger.warning(f"Error updating custom property '{property_name}': {e}")

    return settings_changed
