# Synthetic dataset: what each row exercises

SYNTHETIC. All flights, dates and rates are invented. Row numbers are 1-based
positions in `job_log.csv`.

| Row | Exercises | Expected tier |
|---|---|---|
| 1 | Clean, priced from stated fields | firm |
| 2 | ISO date, 12-hour times | firm |
| 3 | Same as row 2 after normalising the date format | duplicate |
| 4 | Date with no year, resolved from the batch week | assumed |
| 5 | Same flight number as row 1 on another day (a separate job); end time missing on a flat-rate job; "transit" and "push back" spelling | firm |
| 6 | Unknown aircraft code (E190) on a service priced by category | held |
| 7 | Originating flight (not priced) | held |
| 8 | Two-digit year; "320" via the mapping table | firm |
| 9 | Pro-rata: 38 min is billed per minute; whole 15-minute blocks would give a different amount | firm |
| 10 | Water/Waste logged as Terminator, card prices Transit only | held |
| 11 | Impossible time range (end before start) | held |
| 12 | "T" is ambiguous | held |
| 13 | Note questions the line (aircraft change) | held |
| 14 | "B787" maps to widebody | firm |
| 15 | Service not on the rate card | held |
