# Drop everything the scan scenarios touch, so each scenario starts from a
# known database rather than from the previous scenario's leftovers.
delete Scan;
delete IdempotencyRecord;
delete ReceiptItem;
delete PersonaEvent;
delete AuditLog;
delete Event;
delete EventTicket;
delete User;
