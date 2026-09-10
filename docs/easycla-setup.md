# EasyCLA Setup

Codex can maintain `CLA.md` and `CONTRIBUTING.md`, but it cannot enroll the
project in Linux Foundation EasyCLA. A project maintainer with Linux Foundation
and GitHub organization access must complete the steps below before the public
repo flip.

## Manual activation steps

1. Sign in to Linux Foundation Identity:
   `https://identity.linuxfoundation.org`.
2. Open the Project Control Center:
   `https://projectadmin.lfx.linuxfoundation.org`.
3. Create or select the `signal-bench` project.
4. Enable EasyCLA for the project.
5. Create a CLA group for `signal-bench`.
6. Use the Individual CLA text from `CLA.md` as the project CLA text.
7. Add a Corporate CLA only if Agoo AI wants employer-authorized contributions
   at launch.
8. Connect the GitHub organization `narteyb` to the CLA group.
9. Install or authorize the EasyCLA GitHub application when prompted.
10. Enable EasyCLA enforcement for `narteyb/signal-bench`.
11. Copy the generated contributor signing URL and update `CONTRIBUTING.md` if
    maintainers want a direct signing link in addition to the pull-request
    check link.
12. Open a test pull request from an unsigned account and confirm the EasyCLA
    status check blocks the PR.
13. Complete the signing flow from that account and confirm the check clears.
14. Add the EasyCLA status check to the required checks for the protected
    `main` branch.

## Release checklist

- [ ] EasyCLA project exists in Linux Foundation Project Control Center.
- [ ] `narteyb` GitHub organization is connected.
- [ ] `narteyb/signal-bench` has EasyCLA enforcement enabled.
- [ ] Contributor signing URL is present in `CONTRIBUTING.md`.
- [ ] Unsigned test PR is blocked.
- [ ] Signed test PR clears the EasyCLA check.
- [ ] EasyCLA status is required before merge to `main`.

Keep `docs/m5-release-runbook.md` as the broader release runbook. This file is
the narrow EasyCLA activation checklist.
