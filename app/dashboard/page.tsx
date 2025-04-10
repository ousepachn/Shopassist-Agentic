'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { Providers } from '../providers';
import { Dashboard } from '@/components/Dashboard';

function DashboardContent() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.push('/login');
    }
  }, [user, loading, router]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  if (!user) {
    return null; // Will redirect in useEffect
  }

  return <Dashboard />;
}

export default function DashboardPage() {
  return (
    <Providers>
      <DashboardContent />
    </Providers>
  );
} 