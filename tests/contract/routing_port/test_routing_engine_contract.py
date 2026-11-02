"""pytest-bdd binding: the routing-port contract suite (DESIGN brief §6, DEVOPS D95; moved here by DISTILL D181).

Pending until slice 06a/06b. The same checks run against the recorded Valhalla 3.9.1 answers (respx, CI), the
offline road map (MockRoutingProvider) and, with --run-external, the live Valhalla on the Pi (make contract-live).
Fixtures: copy spike/fixtures/ to tests/contract/fixtures/valhalla-3.9.1/ with a sha256 manifest at slice 06a.
"""

from pathlib import Path

from pytest_bdd import scenarios

scenarios("routing-engine-contract.feature", features_base_dir=Path(__file__).parent)
