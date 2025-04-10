'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Providers } from './providers';
import { useAuth } from '@/contexts/AuthContext';

function Home() {
  const router = useRouter();
  const { user, loading } = useAuth();

  useEffect(() => {
    if (!loading) {
      if (user) {
        router.push('/dashboard');
      } else {
        router.push('/login');
      }
    }
  }, [user, loading, router]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  return null; // Will redirect in useEffect
}

export default function HomeWrapper() {
  return (
    <Providers>
      <Home />
    </Providers>
  );
} 