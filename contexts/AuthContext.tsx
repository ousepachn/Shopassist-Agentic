'use client'

import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { initializeApp, getApps } from 'firebase/app'
import { 
  getAuth, 
  onAuthStateChanged, 
  User,
  GoogleAuthProvider,
  signInWithPopup,
  signOut as firebaseSignOut
} from 'firebase/auth'

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
} as const

// Verify Firebase configuration
const verifyConfig = () => {
  const requiredFields = [
    'apiKey',
    'authDomain',
    'projectId',
    'storageBucket',
    'messagingSenderId',
    'appId'
  ] as const

  const missingFields = requiredFields.filter(field => !firebaseConfig[field])
  if (missingFields.length > 0) {
    throw new Error(`Missing Firebase configuration fields: ${missingFields.join(', ')}`)
  }

  console.log('Firebase configuration:', {
    authDomain: firebaseConfig.authDomain,
    projectId: firebaseConfig.projectId
  })
}

verifyConfig()

// Initialize Firebase only if it hasn't been initialized yet
const app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApps()[0]
const auth = getAuth(app)

type AuthContextType = {
  user: User | null
  loading: boolean
  error: string | null
  signInWithGoogle: () => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  error: null,
  signInWithGoogle: async () => {},
  signOut: async () => {},
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      console.log('Auth state changed:', user?.email)
      setUser(user)
      setLoading(false)
      setError(null)
    })

    return () => unsubscribe()
  }, [])

  const signInWithGoogle = async () => {
    setError(null)
    const provider = new GoogleAuthProvider()
    try {
      console.log('Starting Google sign in...')
      const result = await signInWithPopup(auth, provider)
      console.log('Sign in successful:', result.user.email)
    } catch (error: any) {
      console.error('Error signing in with Google:', error)
      setError(error.message)
      throw error
    }
  }

  const signOut = async () => {
    setError(null)
    try {
      await firebaseSignOut(auth)
    } catch (error: any) {
      console.error('Error signing out:', error)
      setError(error.message)
      throw error
    }
  }

  return (
    <AuthContext.Provider value={{ user, loading, error, signInWithGoogle, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
} 