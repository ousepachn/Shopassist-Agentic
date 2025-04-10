'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/contexts/AuthContext'
import { Providers } from '../providers'

function LoginContent() {
  const { user, loading, error, signInWithGoogle } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!loading && user) {
      router.push('/dashboard')
    }
  }, [user, loading, router])

  const handleSignIn = async () => {
    try {
      await signInWithGoogle()
      // Redirection will be handled by the useEffect hook
    } catch (error) {
      console.error('Failed to sign in:', error)
    }
  }

  if (loading) {
    return <div>Loading...</div>
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <div className="max-w-md w-full space-y-8 p-8 bg-white rounded-lg shadow-md">
        <div className="text-center">
          <h2 className="text-3xl font-bold text-gray-900">Welcome to ShopAssist</h2>
          <p className="mt-2 text-gray-600">Please sign in to continue</p>
        </div>
        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded">
            {error}
          </div>
        )}
        <button
          onClick={handleSignIn}
          className="w-full flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
        >
          Sign in with Google
        </button>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Providers>
      <LoginContent />
    </Providers>
  )
} 