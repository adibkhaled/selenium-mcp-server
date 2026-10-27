# Example login requirements

This is sample input for `autopilot plan`; it is not a claim about a particular application.

## Acceptance criteria

- Given a valid, active test account, submitting its credentials signs the user in.
- After successful sign-in, the application displays the authenticated landing page.
- Submitting invalid credentials does not sign the user in.
- The application displays a user-facing error when sign-in is rejected.

## Test constraints

- Use only an approved non-production test environment and synthetic test accounts.
- Do not put real credentials in this file or generated source code.
- The exact rejected-login message is unspecified; record that as an ambiguity rather than inventing its text.
