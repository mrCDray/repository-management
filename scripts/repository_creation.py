import os
import sys
from typing import Dict, Any, List
import logging
import requests
import yaml
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


class RepositoryCreator:
    def __init__(self, github_token, organization):
        self.github_token = github_token
        self.g = Github(github_token)
        self.org = self.g.get_organization(organization)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("repository_create.log")],
        )
        self.logger = logging.getLogger(__name__)
        self.ruleset_manager = RulesetManager(self.logger, self.github_token)

    def load_default_config(self, repository_name):
        """Load the default repository configuration and set the repository name."""
        try:
            with open("default_repository.yml", mode="r", encoding="utf-8") as file:
                config = yaml.safe_load(file)
                repo_config = config.get("repository", {})

                # Set the actual repository name
                repo_config["name"] = repository_name

                return repo_config
        except (FileNotFoundError, yaml.YAMLError) as e:
            self.logger.error(f"Error loading default configuration: {e}")
            return {"name": repository_name}

    def create_repository_config(self, repo_name, config, workspace_path):
        """Create repository configuration file in the repositories directory."""
        try:
            # Create repositories directory if it doesn't exist
            repo_config_dir = os.path.join(workspace_path, "repositories", repo_name)
            os.makedirs(repo_config_dir, exist_ok=True)

            # Prepare configuration file path
            config_file_path = os.path.join(repo_config_dir, "repository.yml")

            # Save configuration
            with open(config_file_path, mode="w", encoding="utf-8") as file:
                yaml.dump(
                    {"repository": config},
                    file,
                    sort_keys=False,
                    Dumper=IndentDumper,
                    default_flow_style=False,
                    indent=2,
                )

            self.logger.info(f"Created repository configuration at {config_file_path}")
            return config_file_path

        except Exception as e:
            self.logger.error(f"Error creating repository configuration: {e}")
            return None

    def create_github_repository(self, repo_name, config):
        """Create a new GitHub repository with the specified configuration."""
        try:
            # Initialize repo variable
            repo = None

            # Check if repository already exists
            try:
                self.org.get_repo(repo_name)
                self.logger.error(f"Repository {repo_name} already exists")
                raise ValueError(f"Repository {repo_name} already exists")
            except GithubException as e:
                # Only proceed if the repository doesn't exist (404 error)
                if e.status != 404:
                    raise e

                # Create new repository
                repo = self.org.create_repo(
                    name=repo_name, private=True, visibility=config.get("visibility", "private").lower(), auto_init=True
                )
                self.logger.info(f"Created new repository {repo_name}")

                # Only apply settings if repository was successfully created
                if repo:
                    try:
                        self._apply_repository_settings(repo, config)
                        # Apply rulesets
                        if "rulesets" in config:
                            self._apply_initial_rulesets(repo, config["rulesets"])
                        return repo
                    except Exception as e:
                        self.logger.error(f"Error creating repository {repo_name}: {e}")
                        return None

        except GithubException as e:
            self.logger.error(f"GitHub API error while creating repository {repo_name}: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error creating repository {repo_name}: {e}")
            raise
        return None

    def _apply_initial_rulesets(self, repo, rulesets):
        """Apply initial rulesets to newly created repository"""
        try:
            for ruleset_config in rulesets:
                ruleset_name = ruleset_config.get("name")
                if not ruleset_name:
                    continue

                # Configure ruleset
                ruleset_params = self.ruleset_manager.configure_ruleset(ruleset_config)

                # Create ruleset using the new method
                success = self.ruleset_manager.create_ruleset(repo, ruleset_params)

                if success:
                    self.logger.info(f"Created ruleset {ruleset_name} for repository {repo.name}")
                else:
                    self.logger.error(f"Failed to create ruleset {ruleset_name} for repository {repo.name}")

        except Exception as e:
            self.logger.error(f"Error applying initial rulesets: {str(e)}")
            raise

    def _apply_repository_settings(self, repo, config):
        """Apply initial settings to the newly created repository."""
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

            self.logger.info(f"Applied settings to repository {repo.name}")

        except Exception as e:
            self.logger.warning(f"Could not apply all repository settings: {e}")
            # Don't raise the exception here as some settings may have been applied successfully


def main():
    # Get environment variables
    github_token = os.environ.get("GITHUB_TOKEN")
    github_org = os.environ.get("GITHUB_ORGANIZATION")
    workspace = os.environ.get("GITHUB_WORKSPACE", os.getcwd())
    repo_name = os.environ.get("REPOSITORY_NAME") or os.environ.get("INPUT_REPOSITORY_NAME")

    if not all([github_token, github_org, repo_name]):
        logging.error("Missing required environment variables")
        sys.exit(1)

    try:
        creator = RepositoryCreator(github_token, github_org)

        # Load default configuration and set repository name
        config = creator.load_default_config(repo_name)

        # Create GitHub repository
        repo = creator.create_github_repository(repo_name, config)

        # Only create configuration file if repository was created successfully
        if repo:
            creator.create_repository_config(repo_name, config, workspace)

    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
