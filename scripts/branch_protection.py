#!/usr/bin/env python3

import logging
import re
from typing import Dict, Any, List

# Configure logging
logger = logging.getLogger("repository_processor")


def parse_list_section(content: str) -> List[str]:
    """Parse a list section (topics or required status checks)."""
    items = []
    if not content:
        return items

    # Check if content is a YAML-style list with hyphens
    if any(line.strip().startswith("- ") for line in content.split("\n")):
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                item = line[2:].strip()
                if item:
                    items.append(item)
    else:
        # Handle comma-separated or space-separated items
        for item in re.split(r"[,\n]", content):
            cleaned_item = item.strip()
            if cleaned_item:
                items.append(cleaned_item)

    return items


def format_branch_references(branch_targets: List[str]) -> List[str]:
    """
    Format branch references to ensure they have the proper refs/heads/ prefix.

    Args:
        branch_targets: List of branch names or patterns

    Returns:
        List of properly formatted branch references
    """
    formatted_refs = []

    # Check if the list looks like it might be a single string that was mistakenly split
    if len(branch_targets) > 3 and all(len(t.strip()) <= 1 for t in branch_targets):
        logger.warning("Detected incorrectly split branch name - attempting to reconstruct")
        reconstructed = "".join(branch_targets).replace(" ", "")
        if reconstructed:
            if not reconstructed.startswith("refs/"):
                reconstructed = f"refs/heads/{reconstructed}"
            formatted_refs.append(reconstructed)
        return formatted_refs

    # Process normal branch targets
    for target in branch_targets:
        if not target:
            continue

        # Keep if already formatted
        if target.startswith("refs/"):
            formatted_refs.append(target)
        else:
            # Add prefix for branch names
            formatted_refs.append(f"refs/heads/{target}")

    return formatted_refs


def create_branch_protection_ruleset(
    name: str, rule_type: str, includes: List[str], excludes: List[str], issue_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Create a branch protection ruleset based on issue form data."""
    # Format branch references to ensure they have the proper prefix
    formatted_includes = format_branch_references(includes) if includes else []
    formatted_excludes = format_branch_references(excludes) if excludes else []

    # Ensure we have at least one include pattern if nothing is specified
    if not formatted_includes:
        formatted_includes = ["refs/heads/main"]
        logger.info("No include patterns specified, defaulting to 'refs/heads/main'")

    ruleset = {
        "name": name,
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": formatted_includes, "exclude": formatted_excludes}},
        "rules": [],
    }

    # Add rules based on the protection type
    rules = []

    # Required status checks
    if issue_data.get("require_status_checks") is True and "required_status_check_list" in issue_data:
        rules.append(
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": issue_data["required_status_check_list"],
                },
            }
        )
    # Required pull request reviews
    if "require_approvals" in issue_data and issue_data["require_approvals"] not in ["0", 0]:
        pr_rule = {
            "type": "pull_request",
            "parameters": {
                "dismiss_stale_reviews_on_push": issue_data.get("dismiss_stale_reviews", False),
                "require_code_owner_review": issue_data.get("require_code_owner_review", False),
                "require_last_push_approval": True,
                "required_approving_review_count": int(issue_data["require_approvals"]),
                "required_review_thread_resolution": True,
            },
        }
        rules.append(pr_rule)

    # Additional rules based on protection level
    if rule_type == "standard-protection":
        # Standard protection includes basic PR review rules if not already added
        if not any(rule.get("type") == "pull_request" for rule in rules):
            rules.append(
                {
                    "type": "pull_request",
                    "parameters": {
                        "required_approving_review_count": 1,
                        "dismiss_stale_reviews_on_push": True,
                        "require_code_owner_review": False,
                    },
                }
            )
        # Add deletion protection
        rules.append({"type": "deletion"})
    elif rule_type == "strict-protection":
        # Strict protection includes enhanced PR rules
        if not any(rule.get("type") == "pull_request" for rule in rules):
            rules.append(
                {
                    "type": "pull_request",
                    "parameters": {
                        "required_approving_review_count": 2,
                        "dismiss_stale_reviews_on_push": True,
                        "require_code_owner_review": True,
                        "require_last_push_approval": True,
                        "required_review_thread_resolution": True,
                    },
                }
            )
        # Add additional protection rules
        rules.append({"type": "deletion"})
        rules.append({"type": "required_linear_history"})
        rules.append({"type": "required_signatures"})

    ruleset["rules"] = rules
    return ruleset


def select_branch_strategy_ruleset(
    config: Dict[str, Any], issue_data: Dict[str, Any], default_config: Dict[str, Any]
) -> Dict[str, Any]:
    """Select the appropriate ruleset based on the branch strategy."""
    # Extract the branch strategy (handling parentheses format)
    branch_strategy = issue_data.get("branch_strategy", "git-flow")

    # Handle empty or "No response" values - default to git-flow
    if not branch_strategy or branch_strategy == "_No response_":
        branch_strategy = "git-flow"
        logger.info("No branch strategy selected, defaulting to git-flow")

    # Clean up format (remove parenthetical info)
    if isinstance(branch_strategy, str) and "(" in branch_strategy:
        branch_strategy = branch_strategy.split("(")[0].strip()

    logger.info(f"Selecting branch strategy ruleset: {branch_strategy}")

    # If strategy is 'custom', keep any custom rulesets from issue_data
    if branch_strategy == "custom":
        logger.info("Using custom branch strategy - applying specific branch rules")
        # Ensure branch_strategy is explicitly set
        config["branch_strategy"] = "custom"
        return config

    # Get branch strategies from default config
    branch_strategies = default_config.get("branch_strategies", {})

    # Use git-flow as the fallback strategy if the selected one doesn't exist
    if branch_strategy not in branch_strategies and branch_strategy != "default":
        logger.warning(f"Branch strategy '{branch_strategy}' not found, defaulting to git-flow")
        branch_strategy = "git-flow"

    # Set the branch strategy in config
    config["branch_strategy"] = branch_strategy

    # Apply ONLY the selected strategy's rulesets, not the entire branch_strategies structure
    if branch_strategy in branch_strategies:
        logger.info(f"Applying branch strategy: {branch_strategy}")
        if "rulesets" in branch_strategies[branch_strategy]:
            config["rulesets"] = branch_strategies[branch_strategy]["rulesets"]
        else:
            logger.warning(f"No rulesets found for {branch_strategy}, using empty set")
            config["rulesets"] = []
    else:
        # Use git-flow as default if nothing else matches
        logger.info("Applying git-flow branch strategy as default")
        if "git-flow" in branch_strategies and "rulesets" in branch_strategies["git-flow"]:
            config["rulesets"] = branch_strategies["git-flow"]["rulesets"]
        else:
            logger.warning("No git-flow rulesets found, using empty set")
            config["rulesets"] = []

    return config


def update_rulesets(config: Dict[str, Any], issue_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update repository rulesets."""
    if "rulesets" not in issue_data or not issue_data["rulesets"]:
        return config

    # Log the rulesets for debugging
    logger.info(f"Processing rulesets from issue data")

    if "rulesets" not in config:
        config["rulesets"] = []

    # Process each ruleset in issue data
    for new_ruleset in issue_data["rulesets"]:
        # Skip if no name provided or if '_No response_' is found
        if not new_ruleset.get("name") or new_ruleset.get("name") == "_No response_":
            logger.warning("Skipping ruleset with no name or '_No response_' value")
            continue

        ruleset_name = new_ruleset.get("name")
        logger.info(f"Processing ruleset: {ruleset_name}")

        # Check if ruleset with same name already exists
        existing_ruleset = next((rule for rule in config["rulesets"] if rule.get("name") == ruleset_name), None)

        if existing_ruleset:
            # Update existing ruleset with new settings
            logger.info(f"Updating existing ruleset: {ruleset_name}")
            update_existing_ruleset(existing_ruleset, new_ruleset)
        else:
            # Add new ruleset
            logger.info(f"Adding new ruleset: {ruleset_name}")
            config["rulesets"].append(new_ruleset)

    return config


def update_existing_ruleset(existing_ruleset: Dict[str, Any], new_ruleset: Dict[str, Any]) -> None:
    """Update an existing ruleset with new settings."""
    # Update top-level properties
    for key, value in new_ruleset.items():
        if key in ("rules", "conditions"):
            continue  # Handle these separately
        existing_ruleset[key] = value

    # Update conditions if present
    if "conditions" in new_ruleset:
        if "conditions" not in existing_ruleset:
            existing_ruleset["conditions"] = {}

        for cond_key, cond_value in new_ruleset["conditions"].items():
            if cond_key == "ref_name":
                # Special handling for ref_name to properly merge includes/excludes
                if "ref_name" not in existing_ruleset["conditions"]:
                    existing_ruleset["conditions"]["ref_name"] = {"include": [], "exclude": []}

                if "include" in cond_value:
                    # Handle string or list format and ensure proper refs/heads/ prefix
                    if isinstance(cond_value["include"], str):
                        branch_refs = parse_list_section(cond_value["include"])
                        formatted_refs = format_branch_references(branch_refs)
                        existing_ruleset["conditions"]["ref_name"]["include"] = formatted_refs
                    else:
                        # Already a list, just ensure proper formatting
                        existing_ruleset["conditions"]["ref_name"]["include"] = format_branch_references(
                            cond_value["include"]
                        )

                if "exclude" in cond_value:
                    # Handle exclude patterns similarly to includes
                    if isinstance(cond_value["exclude"], str):
                        branch_refs = parse_list_section(cond_value["exclude"])
                        formatted_refs = format_branch_references(branch_refs)
                        existing_ruleset["conditions"]["ref_name"]["exclude"] = formatted_refs
                    else:
                        # Already a list
                        existing_ruleset["conditions"]["ref_name"]["exclude"] = format_branch_references(
                            cond_value["exclude"]
                        )
            else:
                existing_ruleset["conditions"][cond_key] = cond_value

    # Handle rules separately if present
    if "rules" in new_ruleset:
        if "rules" not in existing_ruleset:
            existing_ruleset["rules"] = []
        update_ruleset_rules(existing_ruleset["rules"], new_ruleset["rules"])


def update_ruleset_rules(existing_rules: List[Dict[str, Any]], new_rules: List[Dict[str, Any]]) -> None:
    """Update existing ruleset rules with new rules."""
    for new_rule in new_rules:
        if "type" not in new_rule:
            continue

        rule_type = new_rule["type"]
        matching_rule = next((r for r in existing_rules if r.get("type") == rule_type), None)

        if matching_rule:
            # Update existing rule
            logger.info(f"Updating rule type: {rule_type}")
            if "parameters" in new_rule:
                # Create parameters if it doesn't exist
                if "parameters" not in matching_rule:
                    matching_rule["parameters"] = {}

                # Update rule parameters
                for param_key, param_value in new_rule["parameters"].items():
                    matching_rule["parameters"][param_key] = param_value
            else:
                # Update all other rule properties
                for rule_key, rule_value in new_rule.items():
                    if rule_key != "type":  # Don't overwrite the type
                        matching_rule[rule_key] = rule_value
        else:
            # Add new rule
            logger.info(f"Adding new rule type: {rule_type}")
            existing_rules.append(new_rule.copy())
