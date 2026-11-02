# Walking skeleton of feature overland-route-planner-mvp. Executable SSOT (D140); stories in feature-delta.md.
# Exactly ONE @walking_skeleton scenario for the whole feature (D104). Placement (D180): it belongs to slice 01a,
# because its value (a project and trail that survive a restart) is built there; it runs on the planner that
# slices 00a/00b deliver (CI job 2 builds the real web page first, D162). It runs the production composition root in
# a real server process with real HTTP, real storage and real files, in a data folder under the workspace
# (never the OS temp folder, D121). Health and start-up log checks live in slice 00b ("Each start of the planner ...").

@slice-01a
Feature: Marco's trail and places live on his own planner
  As Marco, who keeps his trail collection at home,
  I want the planner running on my own machine to keep my trip project and trails across restarts,
  so I can invest planning evenings in it.

  @walking_skeleton @driving_port @driving_adapter @wiring_e2e @real-io @US-01b @US-02a @J-06
  Scenario: Marco starts his planner, loads his Assietta trail and still finds it after a restart
    Given Marco's planner is running on his home server with his trip collection saved there
    And he has created the project "Alpi Occidentali giugno 2027"
    And he has imported "assietta.gpx" into it
    When the planner is restarted
    Then the planner home page opens
    And the project "Alpi Occidentali giugno 2027" is still listed
    And it still contains track "Strada dell'Assietta" from Pian dell'Alpe to Sestriere
