import { initializeApp, getApps, cert } from 'firebase-admin/app'
import { getFirestore } from 'firebase-admin/firestore'
import { getAuth } from 'firebase-admin/auth'

const firebaseAdminConfig = {
  credential: cert({
    projectId: process.env.FIREBASE_PROJECT_ID,
    clientEmail: process.env.FIREBASE_CLIENT_EMAIL,
    privateKey: process.env.FIREBASE_PRIVATE_KEY?.replace(/\\n/g, '\n')
  })
}

// Initialize Firebase Admin only if it hasn't been initialized
const app = getApps().length ? getApps()[0] : initializeApp(firebaseAdminConfig)

export const adminDb = getFirestore(app)
export const adminAuth = getAuth(app) 