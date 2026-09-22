//+------------------------------------------------------------------+
//|                                    ExportCalendarHistory.mq5      |
//| Exports MetaQuotes' built-in Economic Calendar history to CSV.    |
//| Run this ONCE, LIVE (drag as a Script onto any live chart -       |
//| NOT inside the Strategy Tester - calendar data is empty there).   |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input datetime StartDate  = D'2019.01.01 00:00:00';
input datetime EndDate    = D'2026.12.31 23:59:59';
input string   OutputFile = "calendar_history_full.csv";

string ValStr(MqlCalendarValue &v, int which)
{
   // which: 0=actual 1=forecast 2=prev 3=revised
   bool has = false;
   double val = 0;
   switch(which)
   {
      case 0: has = v.HasActualValue();   if(has) val = v.GetActualValue();   break;
      case 1: has = v.HasForecastValue(); if(has) val = v.GetForecastValue(); break;
      case 2: has = v.HasPreviousValue(); if(has) val = v.GetPreviousValue(); break;
      case 3: has = v.HasRevisedValue();  if(has) val = v.GetRevisedValue();  break;
   }
   return has ? DoubleToString(val, 4) : "";
}

void OnStart()
{
   int handle = FileOpen(OutputFile, FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(handle == INVALID_HANDLE)
   {
      Print("Failed to open output file. Error: ", GetLastError());
      return;
   }

   FileWrite(handle, "event_id", "event_name", "country_code", "currency",
             "importance", "time_utc", "actual", "forecast", "previous", "revised_previous");

   int total_written = 0;
   datetime chunk_start = StartDate;

   while(chunk_start < EndDate)
   {
      datetime chunk_end = chunk_start + 30*24*60*60; // ~30 days per chunk
      if(chunk_end > EndDate) chunk_end = EndDate;

      MqlCalendarValue values[];
      // country_code=NULL, currency=NULL -> pulls every event, every country
      bool ok = CalendarValueHistory(values, chunk_start, chunk_end, NULL, NULL);
      int n = ArraySize(values);

      if(!ok)
         Print("CalendarValueHistory reported an error for chunk starting ",
               TimeToString(chunk_start), " - error code: ", GetLastError());

      for(int i = 0; i < n; i++)
      {
         MqlCalendarEvent ev;
         if(!CalendarEventById(values[i].event_id, ev))
            continue;

         MqlCalendarCountry country;
         CalendarCountryById(ev.country_id, country);

         FileWrite(handle,
                    values[i].event_id,
                    ev.name,
                    country.code,
                    country.currency,
                    (int)ev.importance,
                    TimeToString(values[i].time, TIME_DATE|TIME_SECONDS),
                    ValStr(values[i], 0),
                    ValStr(values[i], 1),
                    ValStr(values[i], 2),
                    ValStr(values[i], 3)
                    );
         total_written++;
      }

      Print("Processed ", TimeToString(chunk_start), " -> ", TimeToString(chunk_end),
            "  (", n, " events this chunk, running total: ", total_written, ")");

      chunk_start = chunk_end;
   }

   FileClose(handle);
   Print("DONE. Total events written: ", total_written);
   Print("File saved in the shared Common Files folder as: ", OutputFile);
   Print("Full path is usually: C:\\Users\\<user>\\AppData\\Roaming\\MetaQuotes\\Terminal\\Common\\Files\\", OutputFile);
}