# M5 release runbook - EasyCLA activation

This runbook covers the maintainer-side EasyCLA activation steps for
`narteyb/signal-bench`. It documents the out-of-repo work that cannot be
completed by a code change in this repository.

EasyCLA v2 is configured through the Linux Foundation Project Control Center.
As of the current Linux Foundation documentation, project managers create CLA
groups, connect GitHub organizations, and enforce CLA checks on repositories in
that UI. No current repo-side `.easycla.yaml` schema was found during T6.4
recon.

## Activation steps

1. **Confirm Linux Foundation access.** Dan's Linux Foundation account at
   `https://identity.linuxfoundation.org` must have the role needed to manage
   the signal-bench project in the Project Control Center.

2. **Create or locate the project.** Sign in to
   `https://projectadmin.lfx.linuxfoundation.org`, create or select the
   `signal-bench` project, and enable EasyCLA from the project's tool status
   area.

3. **Create the CLA group.** In EasyCLA, create a CLA group for signal-bench.
   Use Apache 2.0-compatible Individual CLA terms. Enable Corporate CLA only if
   Dan wants employer-authorized contributions at launch.

4. **Connect the GitHub organization.** Add the GitHub organization `narteyb`
   to the CLA group. Install the EasyCLA GitHub application when prompted and
   grant the permissions requested by EasyCLA for pull-request status checks.

5. **Enforce CLA on the repository.** In the GitHub repositories list for the
   connected organization, enable CLA enforcement for `narteyb/signal-bench`.
   Confirm the repository shows as connected and enforced in the Project Control
   Center.

6. **Capture the contributor URL.** Copy the project-specific contributor
   signing URL from EasyCLA. If maintainers want a direct signing link in the
   repository, update `CONTRIBUTING.md`; otherwise contributors can use the link
   attached to their first EasyCLA pull-request check.

7. **Smoke test the check.** Open a small test PR from a secondary GitHub
   account or ask a collaborator to do it. Confirm the EasyCLA check appears,
   blocks an unsigned contributor, links to the signing flow, and clears after
   signature.

8. **Protect the merge path.** In GitHub branch protection or repository rules,
   require the EasyCLA status check on `main` once the smoke test passes.
   Confirm existing `test` and `lint` workflows remain required if they are
   already part of the release gate.

9. **Flip public when ready.** After EasyCLA, tests, lint, README, and
   CONTRIBUTING are all release-ready, the repo can be made public for the M5
   release tied to Post 1.

Estimated activation time: 30-60 minutes after account access is ready.

## Verification checklist

- [ ] Dan can access the signal-bench project in the Linux Foundation Project
      Control Center.
- [ ] EasyCLA is enabled for the project.
- [ ] GitHub organization `narteyb` is connected.
- [ ] Repository `narteyb/signal-bench` has CLA enforcement enabled.
- [ ] Test PR from an unsigned contributor is blocked by EasyCLA.
- [ ] Signing through EasyCLA clears the PR check.
- [ ] EasyCLA status is required before merge on `main`.
- [ ] `CONTRIBUTING.md` contains the final project-specific EasyCLA signing URL.
