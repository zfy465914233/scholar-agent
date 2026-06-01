# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Scholar Agent, please report it responsibly.

**Do not** open a public GitHub issue for security vulnerabilities.

Instead, please:

1. Open a **private security advisory** on GitHub:
   [https://github.com/zfy465914233/scholar-agent/security/advisories/new](https://github.com/zfy465914233/scholar-agent/security/advisories/new)

2. Or email the maintainer directly with details of the vulnerability.

Please include:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

## Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 7 days
- **Fix**: Depends on severity; critical issues will be prioritized

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | Yes       |

## Scope

This policy covers security vulnerabilities in the Scholar Agent codebase, including:

- The MCP server and its tool endpoints
- File system operations (knowledge base, paper notes, indexes)
- Input validation and schema enforcement
- Dependency vulnerabilities

The following are **out of scope**:

- Issues in dependencies themselves (report upstream)
- Social engineering or phishing
- Denial of service attacks against public APIs used by Scholar Agent
