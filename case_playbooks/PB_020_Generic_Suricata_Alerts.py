# Playbook for IRIS-SOAR
# Created by: Martin Offermann
#
# This is a playbook used by IRIS-SOAR
# It is used to generally handle Suricata Alerts of IBM QRadar alerts.
#
# Acceptable Alerts:
#  - Alerts from IBM QRadar that have a Suricata Alert
#
# Gathered Context:
# - ContextLog, ContextFlow
#
# Actions:
# - Add notes to related iris-cases
#
PB_NAME = "PB_020_Generic_Suricata_Alerts"
PB_VERSION = "0.0.1"
PB_AUTHOR = "Martin Offermann"
PB_LICENSE = "MIT"
PB_ENABLED = True

from lib.class_helper import CaseFile, AuditLog, Alert, ContextLog, ContextFlow, ContextFile, Rule
from lib.logging_helper import Log
from lib.config_helper import Config
from lib.generic_helper import format_results, dict_get

# Prepare the logger
cfg = Config().cfg
log_level_file = cfg["integrations"]["ibm_qradar"]["logging"]["log_level_file"]
log_level_stdout = cfg["integrations"]["ibm_qradar"]["logging"]["log_level_stdout"]
mlog = Log("playbooks." + PB_NAME, log_level_file, log_level_stdout)


def irsoar_can_handle_alert(case_file: CaseFile) -> bool:
    """Checks if this playbook can handle the alert.

    Args:
        case_file (CaseFile): The alert case

    Returns:
        bool: True if the playbook can handle the alert, False if not
    """
    if PB_ENABLED == False:
        mlog.info(f"Playbook '{PB_NAME}' is disabled. Not handling alert.")
        return False

    for alert in case_file.alerts:
        # Check if any of the detecions of the alert case is a QRadar Offense
        try:
            case_file.get_iris_case_number()
        except ValueError:
            mlog.info(f"Playbook '{PB_NAME}' cannot handle alert '{alert.name}' ({alert.uuid}), as there is noiris-casein it.")
            return False

        if alert.vendor_id == "IBM QRadar":
            for log in case_file.context_logs:
                if (
                    dict_get(log.custom_fields, "Alert - Signature") != None
                    and dict_get(log.custom_fields, "Alert - Action") != "store"
                ):
                    mlog.info(f"Playbook '{PB_NAME}' can handle alert '{alert.name}' ({alert.uuid}).")
                    return True
    mlog.info(f"Playbook '{PB_NAME}' cannot handle alert '{alert.name}' ({alert.uuid}).")
    return False


def irsoar_handle_alert(case_file: CaseFile, DRY_RUN=False) -> CaseFile:
    """Handles the alert.

    Args:
        case_file (CaseFile): The alert case
        DRY_RUN (bool, optional): If True, no external changes will be made. Defaults to False.

    Returns:
        CaseFile: The alert case with the context processes
    """
    alert_title = case_file.get_title()
    alerts_to_handle = []
    for alert in case_file.alerts:
        if alert.vendor_id == "IBM QRadar":
            mlog.debug(f"Adding alert: '{alert.name}' ({alert.uuid}) to list.")
            alerts_to_handle.append(alert)

    if len(alerts_to_handle) == 0:
        mlog.critical("Found no alerts in alert case to handle.")
        return case_file

    alert: Alert = alerts_to_handle[0]  # We primarily handle the first alert

    # Add rule information to alert
    current_action = AuditLog(
        PB_NAME,
        1,
        "Adding suricata rule information to alert.",
        "Adding new rules to the alert by parsing the Suricata Alert fields from the gathered ContextLogs",
    )
    case_file.update_audit(current_action, logger=mlog)

    rules_new = []

    # The following fields are parsed from the Suricata Alert:
    #           '"Alert - Created"',
    #            '"Alert - Action"',
    #            '"Alert - Category"',
    #            '"Alert - Domain"',
    #            '"Alert - SID"',
    #            '"Alert - Severity"',
    #            '"Alert - Signature"',
    #            '"Alert - Updated"',

    for log in case_file.context_logs:
        custom_fields = log.custom_fields
        if dict_get(custom_fields, "Alert - Signature") != None:
            rule = Rule(
                dict_get(custom_fields, "Alert - SID", "Unknown"),
                custom_fields["Alert - Signature"],
                custom_fields["Alert - Severity"],
                description="Category: " + custom_fields["Alert - Category"],
                tags=["Suricata", custom_fields["Alert - Category"]],
                raw=str(custom_fields),
                updated_at=dict_get(custom_fields, "Alert - Updated"),
            )
            rules_new.append(rule)
            # TODO: Add 'query' of Suricata rules from external source

    alert.rules.append(rules_new)
    case_file.update_audit(current_action.set_successful(message="Successfully added rules to alert."), logger=mlog)

    # Add note to related iris-case
    current_action = AuditLog(PB_NAME, 2, "Adding note to related iris_case.", "Adding note with new Rules to related iris_case.")
    case_file.update_audit(current_action, logger=mlog)

    iris_case_number = case_file.get_iris_case_number()
    if iris_case_number is None:
        mlog.critical("Could not findiris-casenumber in alert case.")
        case_file.update_audit(current_action.set_error(message="Could not findiris-casenumber in alert case."), logger=mlog)
        return case_file

    note_title = "Suricata Alert Rules"
    if len(rules_new) == 0:
        note_title += " (empty)"
        case_file.update_audit(
            current_action.set_warning(warning_message="No Suricata rules were found. Adding empty note."), logger=mlog
        )

    note_body = "<h2>Suricata Alert Rules</h2>"
    note_body += "<p>These are the Suricata Alert Rules that were parsed from the ContextLogs:</p>"
    note_body += "<br><br>"
    note_body += format_results(rules_new, "html", "")

    article_id = irsoar_add_note_to_iris_case(iris_case_number, "raw", DRY_RUN, note_title, note_body, "text/html")
    if article_id is None:
        mlog.critical(f"Could not add note toiris-case'{iris_case_number}'.")
        case_file.update_audit(
            current_action.set_error(message=f"Could not add note toiris-case'{iris_case_number}'."), logger=mlog
        )
        return case_file
    case_file.update_audit(
        current_action.set_successful(message=f"Successfully added note toiris-case'{iris_case_number}'."), logger=mlog
    )

    # Updateiris-casetitle to include the Suricata Alert Signature
    current_action = AuditLog(
        PB_NAME, 3, "Updatingiris-casetitle.", "Updatingiris-casetitle to include the Suricata Alert Signature."
    )
    case_file.update_audit(current_action, logger=mlog)

    if len(rules_new) == 0:
        mlog.critical("Could not updateiris-casetitle, as there are no rules.")
        case_file.update_audit(
            current_action.set_error(message="Could not updateiris-casetitle, as there are no rules."), logger=mlog
        )
        return case_file

    title = "[IRIS-SOAR] Suricata Alert: "
    title_rule = rules_new[0].name
    title += title_rule

    # Search each rule for any other unique rule name that is not the first one
    new_rule_names = []
    for rule in rules_new:
        new_rule_names.append(rule.name)
    new_rule_names = list(set(new_rule_names))

    if len(new_rule_names) > 1:
        for rule_name in new_rule_names:
            if rule_name != title_rule:
                title += ", " + rule_name

    offender = []
    for log in case_file.context_logs:
        if log.source_device is not None:
            offender.append(log.source_device.name)

    if len(offender) == 0:
        offender.append(log.source_ip)
    if len(offender) == 1:
        title += " | Offender: " + str(offender[0])
    else:
        offender = list(set(offender))
        title += " | Offender: " + ", ".join(offender)

    mlog.info(f"Crafted newiris-casetitle: '{title}'")

    iris_case_number = irsoar_update_iris_case_title(case_file, title)
    if iris_case_number is None or type(iris_case_number) == Exception:
        mlog.critical(f"Could not updateiris-case'{iris_case_number}'.")
        case_file.update_audit(current_action.set_error(message=f"Could not updateiris-case'{iris_case_number}'."), logger=mlog)
        return case_file
    case_file.update_audit(
        current_action.set_successful(message=f"Successfully updatediris-case'{iris_case_number}' title to '{title}'."),
        logger=mlog,
    )

    # Update Alert severity
    current_action = AuditLog(PB_NAME, 4, "Updating alert severity.", "Updating alert severity based on Suricata Alert Severity.")
    case_file.update_audit(current_action, logger=mlog)
    max_severity = 0
    for rule in rules_new:
        if rule.severity and int(rule.severity) > max_severity:
            max_severity = int(rule.severity)

    if max_severity > 0:
        alert.severity = max_severity * 10
        case_file.alerts[0] = alert
        case_file.update_audit(
            current_action.set_successful(message=f"Successfully updated alert severity to '{max_severity}'."), logger=mlog
        )
    else:
        case_file.update_audit(
            current_action.set_warning(warning_message="Could not find any severity > 0 to update."), logger=mlog
        )

    return case_file
