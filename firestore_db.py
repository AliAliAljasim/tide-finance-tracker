import os
import firebase_admin
from firebase_admin import credentials, firestore

_cred_path = os.path.join(os.path.dirname(__file__), 'tidefinancialtracker-firebase-adminsdk-fbsvc-1e64efb4f4.json')
cred = credentials.Certificate(_cred_path)
firebase_admin.initialize_app(cred)
fs = firestore.client()
