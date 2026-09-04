/**
 * Generation v2's day bucket: the New York local calendar date of an instant.
 *
 * The zone's offset changes twice a year, so this asks the platform's timezone
 * database rather than applying an offset. `en-CA` formats as YYYY-MM-DD, which
 * is the shape the projection stores.
 */

const formatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'America/New_York',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

export function nyDayBucket(occurredAt: string | Date): string {
  const instant = occurredAt instanceof Date ? occurredAt : new Date(occurredAt);
  return formatter.format(instant);
}
