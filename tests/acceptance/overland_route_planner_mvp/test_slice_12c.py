"""pytest-bdd binding: the slice 12c scenarios checked at the HTTP API, with the real driven adapters, and on the
shell scripts (US-27 to US-30; D299-D311, DISTILL D312).

The feature is `@slice-12c @pending`: `uv run pytest` skips every scenario here; `--run-pending=slice-12c` runs them
(RED until DELIVER). DELIVER adds `--run-pending=slice-12c` to PENDING_FLAGS (.github/workflows/ci.yml) in its last
step and removes `@pending`, as slices 12 and 12b. The `@ui` scenarios are checked by tests/e2e/road-map.spec.ts
(Playwright, CI job 7) and are not bound here.

Layers: `@driving_port` scenarios run the real app from the composition root in-process; `@real-io @adapter-
integration` add the real driven adapter against real I/O (two local fake servers that record each request, real
polygon files, real tileset and change folders); `@script @offline` run the real shell scripts under the
tests/deploy seams. None plans a route, so none is `solver_child`. Mandate 9: no property-based machinery here
(layers 3+ are example-only, sad paths enumerated)."""

import pytest
from pytest_bdd import scenario

FEATURE = "slice-12c-the-planner-knows-its-map.feature"


@pytest.mark.driving_port
@scenario(FEATURE, "The planner names the regions and the date of the served map")
def test_the_planner_names_the_regions_and_the_date_of_the_served_map() -> None:
    """The planner names the regions and the date of the served map."""


@pytest.mark.driving_port
@scenario(FEATURE, "Before the first rebuild from the app the planner gives the map date and no regions")
def test_before_the_first_rebuild_from_the_app_the_planner_gives_the_map_date_and_no_regions() -> None:
    """Before the first rebuild from the app the planner gives the map date and no regions."""


@pytest.mark.driving_port
@scenario(FEATURE, "A region is found in the catalogue by name, with its parent and what the map already covers")
def test_a_region_is_found_in_the_catalogue_by_name_with_its_parent_and_what_the_map_already_covers() -> None:
    """A region is found in the catalogue by name, with its parent and what the map already covers."""


@pytest.mark.driving_port
@scenario(FEATURE, "Two regions with the same name are told apart by their parent")
def test_two_regions_with_the_same_name_are_told_apart_by_their_parent() -> None:
    """Two regions with the same name are told apart by their parent."""


@pytest.mark.driving_port
@scenario(FEATURE, "A search for a region needs at least two letters")
def test_a_search_for_a_region_needs_at_least_two_letters() -> None:
    """A search for a region needs at least two letters."""


@pytest.mark.driving_port
@scenario(FEATURE, "A change is summarised before it is written, and only the chosen region's border is fetched")
def test_a_change_is_summarised_before_it_is_written_and_only_the_chosen_region_s_border_is_fetched() -> None:
    """A change is summarised before it is written, and only the chosen region's border is fetched."""


@pytest.mark.driving_port
@scenario(FEATURE, "Planning a change leaves the served map as it is")
def test_planning_a_change_leaves_the_served_map_as_it_is() -> None:
    """Planning a change leaves the served map as it is."""


@pytest.mark.driving_port
@scenario(FEATURE, "A change that cannot be applied is refused with the reason and nothing is written")
def test_a_change_that_cannot_be_applied_is_refused_with_the_reason_and_nothing_is_written() -> None:
    """A change that cannot be applied is refused with the reason and nothing is written."""


@pytest.mark.driving_port
@scenario(FEATURE, "A region far from the others is information, not a refusal")
def test_a_region_far_from_the_others_is_information_not_a_refusal() -> None:
    """A region far from the others is information, not a refusal."""


@pytest.mark.driving_port
@scenario(FEATURE, "Changing the road map is not offered when the changes cannot be stored")
def test_changing_the_road_map_is_not_offered_when_the_changes_cannot_be_stored() -> None:
    """Changing the road map is not offered when the changes cannot be stored."""


@pytest.mark.driving_port
@scenario(FEATURE, "A change is refused when the changes cannot be stored")
def test_a_change_is_refused_when_the_changes_cannot_be_stored() -> None:
    """A change is refused when the changes cannot be stored."""


@pytest.mark.driving_port
@scenario(FEATURE, "The catalogue is fetched with the planner's name and only region details are asked for")
def test_the_catalogue_is_fetched_with_the_planner_s_name_and_only_region_details_are_asked_for() -> None:
    """The catalogue is fetched with the planner's name and only region details are asked for."""


@pytest.mark.driving_port
@scenario(FEATURE, "The catalogue is kept, so a restarted planner does not ask for it again")
def test_the_catalogue_is_kept_so_a_restarted_planner_does_not_ask_for_it_again() -> None:
    """The catalogue is kept, so a restarted planner does not ask for it again."""


@pytest.mark.driving_port
@scenario(FEATURE, "The catalogue is fetched again after a week")
def test_the_catalogue_is_fetched_again_after_a_week() -> None:
    """The catalogue is fetched again after a week."""


@pytest.mark.driving_port
@scenario(FEATURE, "The kept catalogue is used when the region service does not answer")
def test_the_kept_catalogue_is_used_when_the_region_service_does_not_answer() -> None:
    """The kept catalogue is used when the region service does not answer."""


@pytest.mark.driving_port
@scenario(FEATURE, "The size of a region is remembered")
def test_the_size_of_a_region_is_remembered() -> None:
    """The size of a region is remembered."""


@pytest.mark.driving_port
@scenario(FEATURE, "The served map is the one whose map data carries the date the Pi reports")
def test_the_served_map_is_the_one_whose_map_data_carries_the_date_the_pi_reports() -> None:
    """The served map is the one whose map data carries the date the Pi reports."""


@pytest.mark.driving_port
@scenario(FEATURE, "After a rollback the older map is the one served")
def test_after_a_rollback_the_older_map_is_the_one_served() -> None:
    """After a rollback the older map is the one served."""


@pytest.mark.driving_port
@scenario(FEATURE, "A map whose regions cannot be read is unknown, never an error")
def test_a_map_whose_regions_cannot_be_read_is_unknown_never_an_error() -> None:
    """A map whose regions cannot be read is unknown, never an error."""


@pytest.mark.driving_port
@scenario(FEATURE, "A damaged region border is reported as a reason, and the map stays unknown")
def test_a_damaged_region_border_is_reported_as_a_reason_and_the_map_stays_unknown() -> None:
    """A damaged region border is reported as a reason, and the map stays unknown."""


@pytest.mark.driving_port
@scenario(FEATURE, "While the Pi is busy building, the last known map is still named")
def test_while_the_pi_is_busy_building_the_last_known_map_is_still_named() -> None:
    """While the Pi is busy building, the last known map is still named."""


@pytest.mark.driving_port
@scenario(FEATURE, "A pending change is kept ready for the helper")
def test_a_pending_change_is_kept_ready_for_the_helper() -> None:
    """A pending change is kept ready for the helper."""


@pytest.mark.driving_port
@scenario(FEATURE, "A cancelled change can no longer be taken by the helper")
def test_a_cancelled_change_can_no_longer_be_taken_by_the_helper() -> None:
    """A cancelled change can no longer be taken by the helper."""


@pytest.mark.driving_port
@scenario(FEATURE, "A place is inside or outside the map by the borders of the regions, not by boxes")
def test_a_place_is_inside_or_outside_the_map_by_the_borders_of_the_regions_not_by_boxes() -> None:
    """A place is inside or outside the map by the borders of the regions, not by boxes."""


@pytest.mark.driving_port
@scenario(FEATURE, "A trail is outside when its entry or its exit is outside, the middle does not matter")
def test_a_trail_is_outside_when_its_entry_or_its_exit_is_outside_the_middle_does_not_matter() -> None:
    """A trail is outside when its entry or its exit is outside, the middle does not matter."""


@pytest.mark.driving_port
@scenario(FEATURE, "Without the regions of the map the planner says the coverage is unknown and warns nothing")
def test_without_the_regions_of_the_map_the_planner_says_the_coverage_is_unknown_and_warns_nothing() -> None:
    """Without the regions of the map the planner says the coverage is unknown and warns nothing."""


@pytest.mark.driving_port
@scenario(FEATURE, "A pending change does not alter what the trip is judged against")
def test_a_pending_change_does_not_alter_what_the_trip_is_judged_against() -> None:
    """A pending change does not alter what the trip is judged against."""


@pytest.mark.driving_port
@scenario(FEATURE, "Stops in areas not linked by land are grouped, and the groups are named")
def test_stops_in_areas_not_linked_by_land_are_grouped_and_the_groups_are_named() -> None:
    """Stops in areas not linked by land are grouped, and the groups are named."""


@pytest.mark.driving_port
@scenario(FEATURE, "Italy, southern France and Spain are linked by land")
def test_italy_southern_france_and_spain_are_linked_by_land() -> None:
    """Italy, southern France and Spain are linked by land."""


@pytest.mark.driving_port
@scenario(FEATURE, "Without southern France Spain is on its own")
def test_without_southern_france_spain_is_on_its_own() -> None:
    """Without southern France Spain is on its own."""


@pytest.mark.driving_port
@scenario(FEATURE, "The map settings no longer name a road-map area and say whether place search is offered")
def test_the_map_settings_no_longer_name_a_road_map_area_and_say_whether_place_search_is_offered() -> None:
    """The map settings no longer name a road-map area and say whether place search is offered."""


@pytest.mark.driving_port
@scenario(FEATURE, "A place name is answered with up to five places, each with its region")
def test_a_place_name_is_answered_with_up_to_five_places_each_with_its_region() -> None:
    """A place name is answered with up to five places, each with its region."""


@pytest.mark.driving_port
@scenario(FEATURE, "No contact detail is ever sent to the search service")
def test_no_contact_detail_is_ever_sent_to_the_search_service() -> None:
    """No contact detail is ever sent to the search service."""


@pytest.mark.driving_port
@scenario(FEATURE, "Nothing is sent to the search service unless a search is asked for")
def test_nothing_is_sent_to_the_search_service_unless_a_search_is_asked_for() -> None:
    """Nothing is sent to the search service unless a search is asked for."""


@pytest.mark.driving_port
@scenario(FEATURE, "Only the typed words reach the search service")
def test_only_the_typed_words_reach_the_search_service() -> None:
    """Only the typed words reach the search service."""


@pytest.mark.driving_port
@scenario(FEATURE, "Two different searches in a row are a second apart")
def test_two_different_searches_in_a_row_are_a_second_apart() -> None:
    """Two different searches in a row are a second apart."""


@pytest.mark.driving_port
@scenario(FEATURE, "The same search again is answered from memory and sends nothing")
def test_the_same_search_again_is_answered_from_memory_and_sends_nothing() -> None:
    """The same search again is answered from memory and sends nothing."""


@pytest.mark.driving_port
@scenario(FEATURE, "Pressing Search twice at once sends one search")
def test_pressing_search_twice_at_once_sends_one_search() -> None:
    """Pressing Search twice at once sends one search."""


@pytest.mark.driving_port
@scenario(FEATURE, "A name that matches nothing is an empty answer, not an error")
def test_a_name_that_matches_nothing_is_an_empty_answer_not_an_error() -> None:
    """A name that matches nothing is an empty answer, not an error."""


@pytest.mark.driving_port
@scenario(FEATURE, "A search service that is busy, down or garbled leaves the trip unchanged")
def test_a_search_service_that_is_busy_down_or_garbled_leaves_the_trip_unchanged() -> None:
    """A search service that is busy, down or garbled leaves the trip unchanged."""


@pytest.mark.driving_port
@scenario(FEATURE, "After a busy answer the search service is left alone for a minute")
def test_after_a_busy_answer_the_search_service_is_left_alone_for_a_minute() -> None:
    """After a busy answer the search service is left alone for a minute."""


@pytest.mark.driving_port
@scenario(FEATURE, "A name shorter than two letters is refused before anything is sent")
def test_a_name_shorter_than_two_letters_is_refused_before_anything_is_sent() -> None:
    """A name shorter than two letters is refused before anything is sent."""


@pytest.mark.driving_port
@scenario(FEATURE, "Switching place search off removes it from the Add menu")
def test_switching_place_search_off_removes_it_from_the_add_menu() -> None:
    """Switching place search off removes it from the Add menu."""


@pytest.mark.driving_port
@scenario(FEATURE, "A search is answered as not available when place search is switched off")
def test_a_search_is_answered_as_not_available_when_place_search_is_switched_off() -> None:
    """A search is answered as not available when place search is switched off."""


@pytest.mark.driving_port
@scenario(FEATURE, "Leaving the search address empty means the usual address, not off")
def test_leaving_the_search_address_empty_means_the_usual_address_not_off() -> None:
    """Leaving the search address empty means the usual address, not off."""


@pytest.mark.driving_port
@scenario(FEATURE, "A result outside the road map joins the trip as a kept, warned place")
def test_a_result_outside_the_road_map_joins_the_trip_as_a_kept_warned_place() -> None:
    """A result outside the road map joins the trip as a kept, warned place."""


@pytest.mark.driving_port
@scenario(FEATURE, "The planner shows the step the helper has reached")
def test_the_planner_shows_the_step_the_helper_has_reached() -> None:
    """The planner shows the step the helper has reached."""


@pytest.mark.driving_port
@scenario(FEATURE, "Planning is paused from the build until the switch ends, and the planner says when it is back")
def test_planning_is_paused_from_the_build_until_the_switch_ends_and_the_planner_says_when_it_is_ba() -> None:
    """Planning is paused from the build until the switch ends, and the planner says when it is back."""


@pytest.mark.driving_port
@scenario(
    FEATURE, "A rebuild that stopped for lack of space says so, with the numbers, and the served map is untouched"
)
def test_a_rebuild_that_stopped_for_lack_of_space_says_so_with_the_numbers_and_the_served_map_is_un() -> None:
    """A rebuild that stopped for lack of space says so, with the numbers, and the served map is untouched."""


@pytest.mark.driving_port
@scenario(FEATURE, "Every way a rebuild can fail is told in plain words, not as a code")
def test_every_way_a_rebuild_can_fail_is_told_in_plain_words_not_as_a_code() -> None:
    """Every way a rebuild can fail is told in plain words, not as a code."""


@pytest.mark.driving_port
@scenario(FEATURE, "A rebuild that ended well shows the new regions and date once the new map is served")
def test_a_rebuild_that_ended_well_shows_the_new_regions_and_date_once_the_new_map_is_served() -> None:
    """A rebuild that ended well shows the new regions and date once the new map is served."""


@pytest.mark.driving_port
@scenario(FEATURE, "Refresh map data asks for the same regions and shows the same cost")
def test_refresh_map_data_asks_for_the_same_regions_and_shows_the_same_cost() -> None:
    """Refresh map data asks for the same regions and shows the same cost."""


@pytest.mark.driving_port
@scenario(FEATURE, "Only one change is pending at a time")
def test_only_one_change_is_pending_at_a_time() -> None:
    """Only one change is pending at a time."""


@pytest.mark.driving_port
@scenario(FEATURE, "A planned change cannot be cancelled once the helper has taken it")
def test_a_planned_change_cannot_be_cancelled_once_the_helper_has_taken_it() -> None:
    """A planned change cannot be cancelled once the helper has taken it."""


@pytest.mark.driving_port
@scenario(FEATURE, "A rebuild is refused on a day that already has a map, with the next day and time it may run")
def test_a_rebuild_is_refused_on_a_day_that_already_has_a_map_with_the_next_day_and_time_it_may_run() -> None:
    """A rebuild is refused on a day that already has a map, with the next day and time it may run."""


@pytest.mark.driving_port
@scenario(FEATURE, "A new map left behind by a failed switch uses the day up")
def test_a_new_map_left_behind_by_a_failed_switch_uses_the_day_up() -> None:
    """A new map left behind by a failed switch uses the day up."""


@pytest.mark.driving_port
@scenario(FEATURE, "A rebuild that failed before the switch leaves no map, so the day is not used up")
def test_a_rebuild_that_failed_before_the_switch_leaves_no_map_so_the_day_is_not_used_up() -> None:
    """A rebuild that failed before the switch leaves no map, so the day is not used up."""


@pytest.mark.driving_port
@scenario(FEATURE, "A start time must be between two minutes and fourteen days ahead")
def test_a_start_time_must_be_between_two_minutes_and_fourteen_days_ahead() -> None:
    """A start time must be between two minutes and fourteen days ahead."""


@pytest.mark.driving_port
@scenario(FEATURE, "Without the helper the planner says rebuilds are not set up and refuses the change")
def test_without_the_helper_the_planner_says_rebuilds_are_not_set_up_and_refuses_the_change() -> None:
    """Without the helper the planner says rebuilds are not set up and refuses the change."""


@pytest.mark.driving_port
@scenario(FEATURE, "The helper counts as set up while it looked less than five minutes ago")
def test_the_helper_counts_as_set_up_while_it_looked_less_than_five_minutes_ago() -> None:
    """The helper counts as set up while it looked less than five minutes ago."""


@pytest.mark.driving_port
@scenario(FEATURE, "A waiting change that the helper has not looked at for minutes says rebuilds are not set up")
def test_a_waiting_change_that_the_helper_has_not_looked_at_for_minutes_says_rebuilds_are_not_set_u() -> None:
    """A waiting change that the helper has not looked at for minutes says rebuilds are not set up."""


@scenario(FEATURE, "The helper is installed once and runs every minute")
def test_the_helper_is_installed_once_and_runs_every_minute() -> None:
    """The helper is installed once and runs every minute."""


@scenario(FEATURE, "A Pi whose app folder name has a space runs the helper too")
def test_a_pi_whose_app_folder_name_has_a_space_runs_the_helper_too() -> None:
    """A Pi whose app folder name has a space runs the helper too."""


@scenario(FEATURE, "Installing again replaces the helper's own job and keeps the Pi's other jobs as they are")
def test_installing_again_replaces_the_helper_s_own_job_and_keeps_the_pi_s_other_jobs_as_they_are() -> None:
    """Installing again replaces the helper's own job and keeps the Pi's other jobs as they are."""


@scenario(FEATURE, "The helper is added beside the Pi's other jobs, which are kept exactly")
def test_the_helper_is_added_beside_the_pi_s_other_jobs_which_are_kept_exactly() -> None:
    """The helper is added beside the Pi's other jobs, which are kept exactly."""


@scenario(FEATURE, "Uninstalling removes only the helper's job")
def test_uninstalling_removes_only_the_helper_s_job() -> None:
    """Uninstalling removes only the helper's job."""


@scenario(FEATURE, "A Pi whose jobs cannot be read is left alone")
def test_a_pi_whose_jobs_cannot_be_read_is_left_alone() -> None:
    """A Pi whose jobs cannot be read is left alone."""


@scenario(FEATURE, "The helper says whether it is installed")
def test_the_helper_says_whether_it_is_installed() -> None:
    """The helper says whether it is installed."""


@scenario(FEATURE, "A Pi that cannot take the helper does not fail the deploy")
def test_a_pi_that_cannot_take_the_helper_does_not_fail_the_deploy() -> None:
    """A Pi that cannot take the helper does not fail the deploy."""


@scenario(FEATURE, "Removing the app from the Pi stops the helper first")
def test_removing_the_app_from_the_pi_stops_the_helper_first() -> None:
    """Removing the app from the Pi stops the helper first."""


@scenario(FEATURE, "A request is taken at its time and the rebuild runs on the regions it names")
def test_a_request_is_taken_at_its_time_and_the_rebuild_runs_on_the_regions_it_names() -> None:
    """A request is taken at its time and the rebuild runs on the regions it names."""


@scenario(FEATURE, "A request is not started before its time")
def test_a_request_is_not_started_before_its_time() -> None:
    """A request is not started before its time."""


@scenario(FEATURE, "A request that is not exactly what the planner writes is refused and nothing runs")
def test_a_request_that_is_not_exactly_what_the_planner_writes_is_refused_and_nothing_runs() -> None:
    """A request that is not exactly what the planner writes is refused and nothing runs."""


@scenario(FEATURE, "The helper cannot reach the internet or the served map")
def test_the_helper_cannot_reach_the_internet_or_the_served_map() -> None:
    """The helper cannot reach the internet or the served map."""


@scenario(FEATURE, "A request cancelled just before the helper looks is not started")
def test_a_request_cancelled_just_before_the_helper_looks_is_not_started() -> None:
    """A request cancelled just before the helper looks is not started."""


@scenario(FEATURE, "A rebuild refused because a deploy is running is tried again the next minute")
def test_a_rebuild_refused_because_a_deploy_is_running_is_tried_again_the_next_minute() -> None:
    """A rebuild refused because a deploy is running is tried again the next minute."""


@scenario(FEATURE, "Two helpers at the same minute: the second leaves at once")
def test_two_helpers_at_the_same_minute_the_second_leaves_at_once() -> None:
    """Two helpers at the same minute: the second leaves at once."""


@scenario(FEATURE, "A rebuild the Pi lost before the switch is recorded as interrupted and the old map serves")
def test_a_rebuild_the_pi_lost_before_the_switch_is_recorded_as_interrupted_and_the_old_map_serves() -> None:
    """A rebuild the Pi lost before the switch is recorded as interrupted and the old map serves."""


@scenario(FEATURE, "A rebuild the Pi lost after the switch is recorded as done")
def test_a_rebuild_the_pi_lost_after_the_switch_is_recorded_as_done() -> None:
    """A rebuild the Pi lost after the switch is recorded as done."""


@scenario(FEATURE, "A rebuild the Pi lost is not touched while a deploy is running")
def test_a_rebuild_the_pi_lost_is_not_touched_while_a_deploy_is_running() -> None:
    """A rebuild the Pi lost is not touched while a deploy is running."""


@scenario(FEATURE, "The rebuild refuses for lack of disk with the numbers, and the helper keeps them")
def test_the_rebuild_refuses_for_lack_of_disk_with_the_numbers_and_the_helper_keeps_them() -> None:
    """The rebuild refuses for lack of disk with the numbers, and the helper keeps them."""


@scenario(FEATURE, "A rebuild from a list of regions downloads each region on its own")
def test_a_rebuild_from_a_list_of_regions_downloads_each_region_on_its_own() -> None:
    """A rebuild from a list of regions downloads each region on its own."""


@scenario(FEATURE, "A region whose border file cannot be fetched stops the rebuild before anything is stopped")
def test_a_region_whose_border_file_cannot_be_fetched_stops_the_rebuild_before_anything_is_stopped() -> None:
    """A region whose border file cannot be fetched stops the rebuild before anything is stopped."""


@scenario(FEATURE, "The rebuild reports its steps in order")
def test_the_rebuild_reports_its_steps_in_order() -> None:
    """The rebuild reports its steps in order."""


@scenario(FEATURE, "The rebuild says nothing about its steps when not asked")
def test_the_rebuild_says_nothing_about_its_steps_when_not_asked() -> None:
    """The rebuild says nothing about its steps when not asked."""


@scenario(FEATURE, "The rebuild builds the list of the map's regions itself, and it travels with the new map")
def test_the_rebuild_builds_the_list_of_the_map_s_regions_itself_and_it_travels_with_the_new_map() -> None:
    """The rebuild builds the list of the map's regions itself, and it travels with the new map."""


@scenario(FEATURE, "The map's integrity check covers its regions and borders too")
def test_the_map_s_integrity_check_covers_its_regions_and_borders_too() -> None:
    """The map's integrity check covers its regions and borders too."""


@scenario(FEATURE, "Seeding a map again still recognises the same tiles after the integrity check grew")
def test_seeding_a_map_again_still_recognises_the_same_tiles_after_the_integrity_check_grew() -> None:
    """Seeding a map again still recognises the same tiles after the integrity check grew."""


@scenario(FEATURE, "The disk the rebuild needs grows with the download")
def test_the_disk_the_rebuild_needs_grows_with_the_download() -> None:
    """The disk the rebuild needs grows with the download."""


@scenario(FEATURE, "A rebuild refused because a deploy is running says so, and reports no failure")
def test_a_rebuild_refused_because_a_deploy_is_running_says_so_and_reports_no_failure() -> None:
    """A rebuild refused because a deploy is running says so, and reports no failure."""
