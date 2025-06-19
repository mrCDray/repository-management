
# Repository Management System - User Guide

This guide will help you use the Repository Management System to create, update, and configure GitHub repositories through issue templates.

## Table of Contents

- [Introduction](#introduction)
- [Getting Started](#getting-started)
- [Creating a New Repository](#creating-a-new-repository)
- [Updating an Existing Repository](#updating-an-existing-repository)
- [Removing Repository Settings](#removing-repository-settings)
- [Understanding Repository Settings](#understanding-repository-settings)
- [Branch Protection Strategies](#branch-protection-strategies)
- [FAQ](#faq)
- [Troubleshooting](#troubleshooting)

## Introduction

The Repository Management System allows you to create and configure GitHub repositories using issue templates rather than manual setup. This ensures consistent configuration across the organization and streamlines the repository creation process.

### Key Features

- Create new repositories with standardized settings
- Update existing repository configurations
- Apply branch protection rules based on best practices
- Configure repository security settings
- Manage repository metadata and features

## Getting Started

### Accessing the Issue Templates

1. Go to the [platform-automations repository](https://github.com/YOUR-ORG/platform-automations)
2. Click on the "Issues" tab
3. Click the "New Issue" button
4. Select one of the repository management templates:
   - "Create New Repository"
   - "Update Repository"
   - "Remove Repository Settings"

## Creating a New Repository

To create a new repository:

1. Open the "Create New Repository" issue template
2. Fill out the required fields (marked with *)
3. Submit the issue
4. The system will process your request and comment on the issue with the results

### Required Fields

| Field | Description | Example |
|-------|-------------|---------|
| Repository Name* | Name of the new repository (lowercase, hyphenated) | `my-new-service` |
| Repository Description | Brief description of the repository | `Backend service for user authentication` |
| Repository Visibility* | Public, Internal, or Private | `Internal` |
| Branch Strategy* | Approach to branch management | `Git Flow` |

### Optional Fields

| Field | Description | Default |
|-------|-------------|---------|
| Template Repository | Repository to use as a template | None |
| Topics | Tags to categorize the repository | None |
| Has Issues | Enable GitHub Issues | True |
| Has Projects | Enable GitHub Projects | False |
| Has Wiki | Enable GitHub Wiki | True |
| Has Discussions | Enable GitHub Discussions | False |
| Security Settings | Vulnerability alerts and automated fixes | Both enabled |

### Example: Creating a New Microservice Repository

```
### Repository Name
api-authentication-service

### Repository Description
Authentication microservice for the customer portal

### Repository Visibility
Internal

### Branch Strategy
Git Flow (main/develop with feature, release, and hotfix branches)

### Template Repository
service-template

### Topics
microservice, authentication, api, java, spring-boot

### Has Issues
true

### Has Wiki
true

### Security Settings
- Enable vulnerability alerts: true
- Enable automated security fixes: true
```

## Updating an Existing Repository

To update an existing repository:

1. Open the "Update Repository" issue template
2. Fill out the repository name and the fields you want to update
3. Leave other fields blank or with "_No response_" to keep current settings
4. Submit the issue
5. The system will process your request and comment on the issue with the results

### Example: Updating Repository Settings

```
### Repository Name
legacy-application

### Action
update

### Repository Description
Updated description for the legacy application with new contact information

### Has Issues
true

### Has Projects
false

### Topics
legacy, maintenance, java, spring
```

## Removing Repository Settings

To remove specific settings from a repository:

1. Open the "Remove Repository Settings" issue template
2. Fill out the repository name and the settings you want to remove
3. Submit the issue
4. The system will process your request and comment on the issue with the results

Note: This does not delete the repository, only removes specific settings.

### Example: Removing Topics and Branch Protection

```
### Repository Name
test-project

### Action
remove

### Topics
outdated-tag, old-framework

### Branch Protection Rule Name
strict-main-protection
```

## Understanding Repository Settings

### Basic Settings

| Setting | Description |
|---------|-------------|
| Description | A brief explanation of the repository's purpose |
| Visibility | Controls who can see the repository (Public, Internal, Private) |
| Topics | Tags to categorize and make the repository discoverable |

### Features

| Feature | Description |
|---------|-------------|
| Issues | Enables GitHub Issues for tracking work |
| Projects | Enables GitHub Projects for project management |
| Wiki | Enables GitHub Wiki for documentation |
| Discussions | Enables GitHub Discussions for community conversations |

### Pull Request Settings

| Setting | Description |
|---------|-------------|
| Allow Squash Merge | Allows squashing commits when merging PRs |
| Allow Merge Commit | Allows standard merge commits |
| Allow Rebase Merge | Allows rebasing and merging PRs |
| Allow Auto Merge | Allows PRs to be merged automatically when requirements are met |
| Delete Branch on Merge | Automatically deletes head branches after merging |
| Allow Update Branch | Shows a button to update a PR branch when the base branch changes |

### Security Settings

| Setting | Description |
|---------|-------------|
| Enable Vulnerability Alerts | Receive alerts for known vulnerabilities in dependencies |
| Enable Automated Security Fixes | Automatically create PRs to resolve vulnerabilities |

## Branch Protection Strategies

The system supports several branch protection strategies, each with its own set of rules and workflows.

### GitHub Flow

A simplified workflow with a single main branch and feature branches.

- **Main Branch**: Protected with required reviews and status checks
- **Feature Branches**: Named with `feature/*` pattern

Best for: Small teams, continuous deployment, web applications

### Git Flow

A more structured workflow with main, develop, feature, release, and hotfix branches.

- **Main/Master Branch**: Heavily protected, represents production code
- **Develop Branch**: Integration branch for features
- **Feature Branches**: For new features, named with `feature/*` pattern
- **Release Branches**: For release preparation, named with `release/x.y.z` pattern
- **Hotfix Branches**: For urgent fixes, named with `hotfix/x.y.z` pattern

Best for: Larger teams, scheduled releases, complex applications

### Trunk-Based Development

A workflow centered around a single "trunk" branch with short-lived feature branches.

- **Trunk/Main Branch**: Protected with required reviews and linear history
- **Feature Branches**: Very short-lived, named with `fb/*` pattern

Best for: CI/CD environments, high-velocity teams

### Feature Branch Workflow

A flexible workflow where features are developed in dedicated branches.

- **Main Branch**: Protected with required reviews and status checks
- **Feature Branches**: Named with various prefixes: `feature/`, `bugfix/`, `improvement/`, etc.

Best for: Teams transitioning from other workflows, mixed development approaches

### GitLab Flow

A workflow that extends GitHub Flow with environment branches.

- **Main Branch**: Protected, represents the latest development code
- **Production Branch**: Represents production code
- **Environment Branches**: For staging, pre-production, etc.
- **Feature Branches**: Named with `feature/*` pattern

Best for: Continuous delivery with multiple environments

### Release Flow

A workflow focused on release management.

- **Main Branch**: Heavily protected, always releasable
- **Release Branches**: Named with `release/date.version` pattern
- **Feature Branches**: Named with `feature/*` pattern

Best for: Teams with complex release requirements

## Custom Branch Protection Rules

For specific protection needs, you can create custom branch protection rules:

1. Select "Custom" as the branch strategy
2. Fill out the "Branch Protection" section of the issue template
3. Specify the branch name pattern, required approvals, and other settings

### Example: Custom Branch Protection

```
### Branch Protection Rule Name
production-branch-protection

### Branch Rule Type
strict-protection

### Branch Includes
main
production

### Require Pull Request Approvals
2

### Require Code Owner Review
true

### Dismiss Stale Reviews
true

### Require Status Checks
true

### Required Status Check List
- build
- test
- security-scan
```

## FAQ

### General Questions

**Q: Who can create or update repositories?**
A: Users with appropriate permissions on the platform-automations repository can create issues. The actual operations are performed by a GitHub App with organization-level permissions.

**Q: Can I delete a repository using this system?**
A: No, the system does not support repository deletion for safety reasons. Contact an organization administrator to delete a repository.

**Q: How long does it take to process a repository request?**
A: Typically, requests are processed within a few minutes. You'll receive a comment on your issue when the operation is complete.

### Repository Settings

**Q: What is the difference between Internal and Private visibility?**
A: Internal repositories are visible to all members of your organization, while Private repositories are only visible to users explicitly granted access.

**Q: Can I change the visibility of a repository later?**
A: Yes, you can update the visibility using the "Update Repository" issue template.

**Q: What happens if I don't specify a branch strategy?**
A: The system will default to Git Flow, which provides a comprehensive branch protection setup.

### Branch Protection

**Q: What does "strict-protection" provide that "standard-protection" doesn't?**
A: Strict protection adds additional safeguards such as required linear history, signed commits, and more reviewers.

**Q: Can I customize branch protection beyond the provided strategies?**
A: Yes, select "Custom" as the branch strategy and fill out the branch protection section with your specific requirements.

**Q: How do I protect multiple branches with different rules?**
A: Create multiple branch protection rules by submitting separate update issues for each rule, or select a branch strategy that includes protection for multiple branches.

## Troubleshooting

### Common Issues

**Issue**: Repository creation fails with an error about the name.
**Solution**: Ensure the repository name follows GitHub's naming convention (lowercase, hyphens, no special characters).

**Issue**: Branch protection rules don't appear to be applied.
**Solution**: Check that you've specified the correct branch names and that the branches exist in the repository.

**Issue**: Update operation doesn't change a setting.
**Solution**: Make sure you've explicitly specified the setting you want to change. Leaving a field blank or with "_No response_" will keep the current value.

### Getting Help

If you encounter issues not covered in this guide:

1. Check the error message in the issue comment for specific details
2. Review this guide for relevant sections
3. Contact the platform team for assistance through the support channel

---

For additional assistance, please contact the platform team.
