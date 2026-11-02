# Slice 06b - compromise legs are used only when needed, and always explained. US-10b (J-01). FR-5.8, FR-8.2.
# Executable SSOT (D140). Ladder: Confirmed -> Unconfirmed (ignores access restrictions | off-network link
# <= 1,500 m) -> None (ADR-016, D44, D59, D79). Offline road map with scripted levels and snap classes.
# The point-classification contract checks moved to tests/contract/routing_port/ (D181).

@slice-06b @pending
Feature: Compromise legs, used only when needed and always explained
  As Marco, I want the planner to reach trail ends that no legal road quite reaches, marking each compromise
  with its reason, so that I know exactly what to check on the ground.

  @US-10b @J-01 @FR-5.8 @edge
  Scenario: A leg that needs a compromise is Unconfirmed and explained
    Given the only road to POI "Rifugio Barbara" is tagged no access
    When Marco recalculates
    Then the leg to "Rifugio Barbara" is Unconfirmed with reason "ignores access restrictions"
    And the Warnings list it as "check on the ground"

  @US-10b @J-01 @FR-5.8 @edge
  Scenario: A trail entry near the road gets a short off-network link
    Given the entry of track "Strada dell'Assietta" is 1.2 km from the nearest road and no Confirmed leg reaches it
    When Marco recalculates
    Then the leg to "Strada dell'Assietta" is Unconfirmed with reason "entry is 1.2 km from the nearest road"

  @US-10b @J-01 @FR-5.8 @FR-8.2 @error
  Scenario: A place too far from any road gets no link
    Given POI "Lago Nero" is 2.1 km from the nearest road and no other leg reaches it
    When Marco recalculates
    Then the run fails with "'Lago Nero' cannot be connected to any other stop"

  @US-10b @J-01 @FR-5.8 @edge
  Scenario Outline: The off-network link stops at 1.5 km
    Given POI "Lago Nero" is <distance> m from the nearest road and no other leg reaches it
    When Marco recalculates
    Then the leg to "Lago Nero" is <outcome>

    Examples:
      | distance | outcome                                                       |
      | 1500     | Unconfirmed with reason "POI is 1.5 km from the nearest road" |
      | 1501     | not connected, and the run fails naming "Lago Nero"           |

  @US-10b @J-01 @FR-5.8 @edge
  Scenario: A Confirmed leg is never replaced by a compromise
    Given a Confirmed leg reaches POI "Rifugio Barbara" and a shorter route exists only through a no-access road
    When Marco recalculates
    Then the leg to "Rifugio Barbara" is Confirmed
    And the Warnings do not mention "Rifugio Barbara"

  @US-10b @J-01 @FR-8.2 @technical @requires_external @real_provider @pi @error
  Scenario: A summit far from any road cannot be connected
    Given the planner routes on Valhalla on Marco's Pi
    And project "Alpi Occidentali giugno 2027" includes POI "Vetta del Monte Bianco" at 45.8326, 6.8652
    When Marco recalculates
    Then the run fails with "'Vetta del Monte Bianco' cannot be connected to any other stop"
