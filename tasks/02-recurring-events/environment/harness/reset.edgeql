# Drop everything the series scenarios touch, so each run starts from a known
# database rather than from the previous candidate's leftovers.
#
# Order matters. The occurrences link carries a Restrict deletion policy, so an
# occurrence still attached to a series cannot be deleted; unlink first. Events
# are referenced by occurrences and by receipt items, so those go before the
# events do.
update EventSeries set { occurrences := {} };
delete EventSeriesOccurrence;
delete EventSeries;
delete EventSeriesRepeatConfig;
delete ReceiptItem;
delete PersonaEvent;
delete AuditLog;
delete Event;
delete EventTicket;
delete UserOrganization;
delete Organization;
delete User;
