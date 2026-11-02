# Slice 00b - the planner on my home Pi, reachable from home only. Story US-01a (J-06). NFR-1, 2, 4, 5, 7.
# Executable SSOT (D140); story text in feature-delta.md (DISCUSS). US-01a moved here from slice 01a (D145).
# Bound to step definitions (steps/platform_steps.py). @pending until DELIVER enables each scenario
# (--run-pending=slice-00b). @requires_external scenarios run with --run-external on the named host:
# the Pi (make acceptance-pi), an amd64 PC, or CI job 7 (-m "compose or security", D170).
# Slice 00a (CI and image) is an enabler without scenarios of its own (D145).

@slice-00b @pending
Feature: The planner on my home Pi, reachable from home only
  As Marco, I want the planner to come up on my home Pi with one command, ask the household for our shared
  password when I want that, and stay inside the home network, so that my trip data stays private.

  @US-01a @J-06 @requires_external @pi @deploy
  Scenario: Marco brings the planner up on his Pi with one command
    Given Marco has copied the planner set-up and his settings file to his Raspberry Pi
    When he starts the planner on the Pi with one command
    Then the planner home page opens at "pi.example" in his desktop browser
    And the health check reports the planner as healthy
    And the start-up is recorded as one line in the planner log

  @US-01a @J-06 @requires_external @pc_amd64 @deploy
  Scenario: The same setup runs on Marco's PC
    Given Marco uses the same planner set-up and settings file on his amd64 PC
    When he starts the planner on the PC with one command
    Then the planner home page opens on the PC

  @US-01a @J-06 @error @driving_port @security
  Scenario: Household members are asked for the shared password when it is switched on
    Given the shared household password is switched on in the settings for user "ferri"
    And Marco has created the project "Alpi Occidentali giugno 2027"
    When Giulia opens the planner from her iPhone without the password
    Then she is asked to log in
    And no project data is shown
    And the health check still answers without revealing any project

  @US-01a @J-06 @error @security
  Scenario: A wrong shared password is refused
    Given the shared household password is switched on in the settings for user "ferri"
    And Marco has created the project "Alpi Occidentali giugno 2027"
    When Giulia opens the planner from her iPhone with a wrong password
    Then she is asked to log in
    And no project data is shown

  @US-01a @J-06 @real-io @deploy
  Scenario: The planner stays on the home network by default
    Given the planner set-up as delivered for the home server
    When Marco checks what the set-up opens to the network by default
    Then only the planner itself can be reached from the home network, at its usual address
    And the routing engine is never reachable from the network
    And the maintenance helpers listen only on the server itself, and only when started on purpose

  @US-01a @J-06 @requires_external @docker @security
  Scenario: Sharing the packaged planner never shares Marco's password
    Given Marco's settings file contains the shared household password
    When anyone inspects the packaged planner built from Marco's folder
    Then the password is not found in it

  @US-01a @J-06 @requires_external @pi @kpi @G1
  Scenario: The idle planner leaves room on the Pi
    Given the planner has been idle for 10 minutes on the Pi
    When Marco checks the planner's memory use, not counting the routing engine
    Then it uses less than 300 MB

  @US-01a @J-06 @technical @wiring_e2e @driving_adapter @real-io
  Scenario: Each start of the planner reports healthy and records one start-up line
    Given Marco's planner is running on his home server with his trip collection saved there
    When the planner is restarted
    Then the health check reports the planner as healthy
    And each start-up was recorded as one line in the planner log
