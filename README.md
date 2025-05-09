# Repository Management System Documentation

## Table of Contents

1. Overview
2. User Guide
3. Technical Documentation

## Overview

The Repository Management System is a GitHub-based solution that allows users to create, configure, and maintain repositories through an issue-based workflow (IssueOps). This approach standardizes repository configurations, enforces best practices, and provides an audit trail for all repository changes.

### Key Features

- **Standardized Repository Creation**: Ensures all repositories follow organizational standards
- **Configuration as Code**: Repository settings stored as YAML files in a central location
- **Self-Service for Teams**: Users can request repository changes without needing admin access
- **Enforced Branch Protection**: Standard branch protection rules applied automatically
- **Automated Security Features**: Security scanning and vulnerability alerts configured by default
- **Audit Trail**: All changes tracked through GitHub issues and commits
- **Branch Rule Management**: Dedicated workflow for managing branch protection rules

### How It Works

1. **Issue Creation**: Users fill out a repository management issue template
2. **Automated Processing**: GitHub Actions workflow processes the issue
3. **Configuration Generation**: System creates/updates repository configuration files
4. **Repository Management**: Another workflow applies configuration to actual GitHub repositories
5. **Feedback Loop**: System comments on the issue with results

## User Guide

### Creating a New Repository

1. Navigate to the "Issues" tab of the platform-automations repository
2. Click "New Issue" and select the "Repository Management" template
3. Fill out the form with the following information:
   - **Action**: Select "create"
   - **Repository Name**: Enter a name (lowercase with hyphens only)
   - **Repository Visibility**: Choose "internal" (recommended) or "private"
   - **Topics**: Optional list of topics to categorize the repository
   - **Feature toggles**: Configure repository features as needed
4. Submit the issue

Example:

```
Action: create
Repository Name: my-new-service
Repository Visibility: internal
Topics:
- project
- Technology
- group-detail
Enable Issues: true
Enable Projects: true
Enable Wiki: false
```

### Updating an Existing Repository

1. Navigate to the "Issues" tab of the platform-automations repository
1. Navigate to the "Issues" tab of the platform-automations repository
2. Click "New Issue" and select the "Repository Management" template
3. Fill out the form with the following information:
   - **Action**: Select "update"
   - **Repository Name**: Enter the exact name of the existing repository
   - **Parameters to update**: Only fill in fields you want to change
4. Submit the issue

Example:

```
Action: update
Repository Name: existing-service
Topics:
- updated-topic
- api-service
Enable Projects: false
Enable Vulnerability Alerts: true
```

### Managing Branch Protection Rules

1. Navigate to the "Issues" tab of the platform-automations repository
2. Click "New Issue" and select the "Repository Management" template
3. Fill out the form with the following information:
   - **Action**: Select "manage-branch-rules"
   - **Repository Name**: Enter the exact name of the existing repository
   - **Branch Name**: Specify the branch to protect (e.g., "main", "develop", or pattern "feature/*")
   - **Branch Rule Type**: Choose a pre-defined rule set or "custom"
   - **Protection Settings**: Configure specific protection settings as needed
4. Submit the issue

Example:

```
Action: manage-branch-rules
Repository Name: existing-service
Branch Name: main
Branch Rule Type: strict-protection
Require Pull Request Approvals: 2
Require Code Owner Review: true
Required Status Checks:
- build
- test
- security-scan
```

#### Available Branch Rule Types

| Rule Type | Description |
|-----------|-------------|
| standard-protection | Basic protection with 1 required review |
| strict-protection | Strict protection with 2 required reviews, signed commits, and more |
| custom | Configure protection settings individually |

### Available Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| Repository Name | Name of the repository (lowercase with hyphens) | Required |
| Repository Visibility | Access level - internal (visible to org) or private | internal |
| Topics | List of topics to categorize the repository | [] |
| Enable Issues | Turn on GitHub Issues for the repository | true |
| Enable Projects | Turn on GitHub Projects for the repository | true |
| Enable Wiki | Turn on GitHub Wiki for the repository | true |
| Allow Squash Merge | Allow squash merging of pull requests | true |
| Allow Merge Commit | Allow standard merge commits | true |
| Allow Rebase Merge | Allow rebase merging of pull requests | true |
| Allow Auto Merge | Allow auto-merging of pull requests | false |
| Delete Branch on Merge | Automatically delete head branches after merging | true |
| Enable Vulnerability Alerts | Enable Dependabot vulnerability alerts | true |
| Enable Automated Security Fixes | Enable automated security fixes | true |
| Branch Name | Name of branch to protect | Required |
| Branch Rule Type | Pre-defined protection level | custom |
| Require Pull Request Approvals | Number of required reviews | 1 |
| Require Code Owner Review | Require review from code owners | false |
| Dismiss Stale Reviews | Dismiss reviews when new commits are pushed | true |
| Require Status Checks | Require status checks to pass | false |
| Required Status Checks | List of required status checks | [] |
| Restrict Push Access | Require signed commits for pushing | false |

### Branch Protection Rules (Applied Automatically)

All repositories get the following branch protection rules automatically:

1. **Main Branch Protection**:
   - Requires 2 approving reviews
   - Requires status checks to pass
   - Prevents force pushes
   - Requires signed commits

2. **Development Branch Protection**:
   - Requires 1 approving review
   - Prevents branch deletion

3. **Feature Branch Protection**:
   - Enforces naming convention (`feature/Feature-name`)
   - Requires 1 approving review

4. **Hotfix Branch Protection**:
   - Enforces naming convention (`hotfix/JIRA-123`)
   - Requires 2 approving reviews

### Troubleshooting

**Issue: Repository configuration not updating**

- Check issue comments for error messages
- Verify you're using the correct repository name
- Ensure you have proper permissions within the organization

**Issue: Invalid repository name error**

- Repository names must be lowercase with hyphens or underscores
- Names must start with a letter or number

**Issue: Branch protection not applied**

- Branch protection is only applied after the repository exists
- Main/master branch must exist before protection is applied

## Technical Documentation

### System Architecture

The Repository Management System uses several components to create a complete workflow:

1. **Issue Template**: Collects user input (`repository-management.yml`)
2. **Processing Workflow**: GitHub Actions workflow to handle issues (`process-repository-issue.yml`)
3. **Processing Script**: Python script that parses issues and creates configs (`process_repository_issue.py`)
4. **Configuration Storage**: YAML files stored in repository.yml
5. **Repository Workflow**: Applies configurations to GitHub (`repository-manage.yml`)
6. **Repository Scripts**: Python scripts that interact with GitHub API (`repository_creation.py`, repository_manage.py)

```
┌────────────────┐    ┌─────────────────────┐    ┌───────────────┐
│ Issue Template │───►│ Processing Workflow │───►│ Config Files  │
└────────────────┘    └─────────────────────┘    └───────┬───────┘
                               │                         │
                      ┌────────▼──────────┐     ┌────────▼────────┐
                      │ Processing Script │     │ Repository      │
                      └─────────┬─────────┘     │ Workflow        │
                                │               └────────┬────────┘
                                │                        │
                                ▼                        ▼
                      ┌─────────────────────────────────────────┐
                      │             GitHub API                  │
                      └─────────────────────────────────────────┘
```

### Repository Configuration Format

Repository configurations are stored as YAML files with the following structure:

```yaml
repository:
  name: repository-name
  visibility: internal
  topics: [topic1, topic2]
  has_issues: true
  has_projects: true
  has_wiki: true
  allow_squash_merge: true
  allow_merge_commit: true
  allow_rebase_merge: true
  allow_auto_merge: false
  delete_branch_on_merge: true
  allow_update_branch: true
  security:
    enableVulnerabilityAlerts: true
    enableAutomatedSecurityFixes: true
  rulesets:
    - name: main-branch-protection
      target: branch
      enforcement: active
      conditions:
        ref_name:
          include: ["refs/heads/main"]
          exclude: []
      rules:
        - type: pull_request
          parameters:
            dismiss_stale_reviews_on_push: true
            require_code_owner_review: true
            required_approving_review_count: 2
            required_review_thread_resolution: true
        - type: required_status_checks
          parameters:
            strict_required_status_checks_policy: true
            required_status_checks:
              - context: build
              - context: test
```

### Key Files and Components

**Issue Template**:
- repository-management.yml: Defines form fields for repository management

**Workflows**:
- process-repository-issue.yml: Processes issues and creates config files
- repository-manage.yml: Applies configuration to GitHub repositories

**Scripts**:
- process_repository_issue.py: Parses issues and generates configs
- repository_manage.py: Updates existing repositories
- repository_creation.py: Creates new repositories

**Configuration**:
- default_repository_config.yml: Default settings template
- repository.yml: Per-repository configurations

### Processing Flow

1. User creates issue using the repository management template
2. process-repository-issue.yml workflow triggers on issue creation/edit
3. process_repository_issue.py script:
   - Parses issue body
   - Validates input data
   - Loads default or existing configuration
   - Updates configuration with issue data
   - Updates branch protection rules if specified
   - Saves configuration to repository.yml
   - Comments on the issue with results
4. repository-manage.yml workflow triggers on changes to config files
5. repository_manage.py script:
   - Identifies changed configuration files
   - Applies changes to GitHub repositories via API
   - Updates branch protection rules

### Branch Protection Management

The system supports managing branch protection rules through:

1. **Pre-defined rule templates**: Standard and strict protection levels
2. **Custom rule configuration**: Fine-grained control of protection settings
3. **Branch pattern support**: Apply rules to specific branches or branch patterns

When processing a "manage-branch-rules" action, the system:
1. Checks if rules already exist for the specified branch
2. Creates or updates the ruleset for that branch
3. Configures all requested protection settings
4. Saves the configuration and applies changes to GitHub

### Adding New Repository Settings

To add support for new GitHub repository settings:

1. Update repository-management.yml with new form fields
2. Modify process_repository_issue.py to handle new fields in `update_config_from_issue_data()`
3. Update repository_manage.py to apply new settings via GitHub API

### Integration Points

- **GitHub REST API**: Used for repository management operations
- **PyGithub Library**: Primary interface for repository operations
- **GitHub Actions**: Workflow automation system
- **GitHub Issues**: User interface for requesting changes

### Error Handling

The system includes comprehensive error handling:

1. Input validation with user-friendly error messages
2. Safe loading of YAML configurations
3. GitHub API error handling with retries
4. Rate limit detection and management
5. Issue comments for feedback on errors

## Best Practices for Extending the System

1. **Maintain Configuration Format**: Keep the YAML structure consistent
2. **Add Validation**: Validate all user inputs thoroughly
3. **Test API Changes**: GitHub API can change, test carefully before deployment
4. **Document New Features**: Update documentation when adding options
5. **Handle Errors Gracefully**: Always provide clear error messages to users
6. **Preserve Existing Settings**: Only update fields specified by the user

---

This repository management system streamlines GitHub repository administration, enforces organizational standards, and enables self-service while maintaining proper governance. For additional assistance or feature requests, please create an issue in the platform-automations repository.
