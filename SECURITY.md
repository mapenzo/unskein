# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x (unreleased) | Yes |

## Reporting a vulnerability

Please **do not** open a public issue. Use GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository ("Security" tab → "Report a vulnerability").

You should receive an acknowledgement within 7 days.

## Scope notes

- `unskein` never executes the code it analyzes; it only parses it with `ast`.
- API keys must never appear in logs or reports. Any leak is a security bug.
- Symlinks are not followed by default, to avoid analyzing code outside the project.
