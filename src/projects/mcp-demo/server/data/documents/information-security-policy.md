# Information Security Policy

## Data Classification
All information is classified into four levels:
1. **Public** – approved for external release (website, published docs).
2. **Internal** – default for company information; share only with employees.
3. **Confidential** – customer data, financials, contracts, source code. Access on a
   need-to-know basis; must be encrypted in transit and at rest.
4. **Restricted** – credentials, encryption keys, payment card data, and government IDs.
   Stored only in approved vaults; never in email, chat, tickets or documents.

## Passwords and Authentication
- Use the company password manager for all work accounts.
- Minimum password length is 14 characters; passphrases are encouraged.
- Multi-factor authentication (MFA) is mandatory for email, source control, cloud consoles and
  the VPN. Hardware security keys are required for production cloud access.
- Never share accounts. Service credentials are issued per service and rotated every 90 days.

## Devices
Company laptops must have full-disk encryption, automatic OS updates and the endpoint
protection agent enabled. Screens lock automatically after 5 minutes of inactivity. Personal
devices may access email and chat only through the managed mobile app; they may not store
Confidential data.

## Access Reviews
Managers review their team's access to production systems every quarter. Access is removed
within 24 hours when an employee leaves or changes role.

## Incident Reporting
Report suspected security incidents (phishing, lost devices, leaked credentials, unexpected
access) to security@northwindlabs.example within **1 hour** of discovery, or in the #security
channel. Do not try to investigate on your own or delete evidence. Lost or stolen laptops must
also be reported to IT so they can be remotely wiped.

## Use of AI Tools
Only approved AI assistants may be used with Internal data. Confidential or Restricted data
must never be pasted into unapproved AI tools or public chatbots. Code generated with AI must go
through normal code review.
