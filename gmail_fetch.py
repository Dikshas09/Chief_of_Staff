import os
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/calendar',]
        
CREDENTIALS_FILE = r'C:\Users\diksh\chief_of_staff\servers\client_secret_98708590862-eg0cc2ktd0ojud37j7f2c5kn04mun4ua.apps.googleusercontent.com.json'
TOKEN_FILE = r'C:\Users\diksh\chief_of_staff\token.json'

def get_gmail_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def get_snippet(body):
    """Extract a short plain-text snippet from the message body."""
    if not body:
        return ""
    data = body.get('data', '')
    import base64
    if data:
        text = base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
        # Remove HTML tags for a clean snippet
        import re
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:120]
    return ""

def main():
    service = get_gmail_service()
    
    # Fetch the 10 most recent threads from inbox
    results = service.users().threads().list(
        userId='me',
        maxResults=10,
        q='in:inbox'
    ).execute()
    
    threads = results.get('threads', [])
    
    if not threads:
        print("No threads found in inbox.")
        return
    
    print(f"{'#':<3} {'Sender':<35} {'Subject':<50} Snippet")
    print("-" * 140)
    
    for idx, thread in enumerate(threads, 1):
        thread_data = service.users().threads().get(userId='me', id=thread['id'], format='full').execute()
        messages = thread_data.get('messages', [])
        
        if not messages:
            continue
        
        first_msg = messages[0]
        headers = first_msg.get('payload', {}).get('headers', [])
        
        sender = ''
        subject = ''
        for h in headers:
            if h['name'] == 'From':
                sender = h['value']
            if h['name'] == 'Subject':
                subject = h['value']
        
        # Truncate for display
        sender_display = sender if len(sender) <= 34 else sender[:31] + '...'
        subject_display = subject if len(subject) <= 49 else subject[:46] + '...'
        
        # Get snippet from message
        snippet = first_msg.get('snippet', '') or ''
        
        print(f"{idx:<3} {sender_display:<35} {subject_display:<50} {snippet[:100]}")

if __name__ == '__main__':
    main()