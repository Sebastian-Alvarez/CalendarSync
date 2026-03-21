import sys
import json
import datetime
import requests
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
# -------------------------------------------------- Var. Globales ------------------------------------------------------------------
SCOPES = ["https://www.googleapis.com/auth/calendar"]
BASE_DIR = Path(__file__).resolve().parent
saCredentials = BASE_DIR / "secrets" / "service-account.json"
calendarID = "a4e2b55b85135005172885d8ae0d81476c38d582d42efcb4883fbd2d08e8e9da@group.calendar.google.com"
# -----------------------------------------------------------------------------------------------------------------------------------
def main():
    try:
        credentials = getCredential()
        service = connectGCal(credentials)
        calendar = service.calendars().get(calendarId=calendarID).execute()
        testConnection(service, calendar)

    except Exception as e:
        print(f"Error inesperado: {e}")
# -----------------------------------------------------------------------------------------------------------------------------------
def getCredential():
    try:
        credential = service_account.Credentials.from_service_account_file(
            str(saCredentials),
            scopes=SCOPES,
        )
        return credential
    except ValueError:
        print("Unable to authenticate using service account key.")
        sys.exit()
def connectGCal(credentials):
    try:
        service = build("calendar", "v3", credentials=credentials)
        return service
    except Exception as e:
        print(f"Error al conectar con Google Calendar: {e}")
        sys.exit()
def testConnection(service, calendar):
    try:
        print(f"Calendario: {calendar['summary']}")
        print(f"Zona horaria: {calendar['timeZone']}")
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        events_result = service.events().list(
            calendarId=calendarID,
            timeMin=now,
            maxResults=5,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])
        print("\nPróximos eventos:")
        if not events:
            print("No hay eventos próximos.")
        else:
            for event in events:
                start = event["start"].get("dateTime", event["start"].get("date"))
                print(f"- {start} | {event.get('summary', '(sin título)')}")
    except HttpError as e:
        print(f"Error HTTP de Google Calendar: {e}")
# -----------------------------------------------------------------------------------------------------------------------------------

# -----------------------------------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    main()