'use client';

import { useAuth } from '@/contexts/AuthContext';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

const API_BASE_URL = 'http://localhost:8000';

interface SearchResult {
  score: number;
  username: string;
  content: string;
  caption: string;
  timestamp: string;
}

export function Search() {
  const { user, signOut } = useAuth();
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(5);
  const [instagramRecipientId, setInstagramRecipientId] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  const handleSignOut = async () => {
    try {
      await signOut();
      router.push('/login');
    } catch (error) {
      console.error('Error signing out:', error);
    }
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!query.trim()) {
      setError('Please enter a search query');
      return;
    }

    if (!instagramRecipientId.trim()) {
      setError('Please enter an Instagram recipient ID');
      return;
    }

    try {
      setIsLoading(true);
      setError(null);
      
      const response = await fetch(`${API_BASE_URL}/api/search`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query,
          top_k: topK,
          instagram_recipient_id: instagramRecipientId
        })
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Search failed');
      }

      setResults(data.results);
    } catch (error) {
      console.error('Error during search:', error);
      setError(error instanceof Error ? error.message : 'Search failed');
      setResults([]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gray-100">
      <div className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        <div className="px-4 py-6 sm:px-0">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex justify-between items-center mb-6">
              <h1 className="text-3xl font-bold text-gray-900">
                ShopAssist Semantic Search
              </h1>
              <div className="flex space-x-4">
                <button
                  onClick={() => router.push('/dashboard')}
                  className="bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors"
                >
                  Dashboard
                </button>
                <button
                  onClick={handleSignOut}
                  className="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600 transition-colors"
                >
                  Sign Out
                </button>
              </div>
            </div>
            
            <div className="space-y-6">
              <p className="text-gray-600">Search for posts using natural language</p>
              <p className="text-sm text-gray-500">Logged in as: {user?.email}</p>
              
              {/* Search Form */}
              <form onSubmit={handleSearch} className="space-y-4">
                <div>
                  <label htmlFor="query" className="block text-sm font-medium text-gray-700">
                    Search Query
                  </label>
                  <input
                    type="text"
                    id="query"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                    placeholder="e.g., recipe for chocolate cake"
                  />
                </div>
                
                <div>
                  <label htmlFor="instagramRecipientId" className="block text-sm font-medium text-gray-700">
                    Instagram Recipient ID
                  </label>
                  <input
                    type="text"
                    id="instagramRecipientId"
                    value={instagramRecipientId}
                    onChange={(e) => setInstagramRecipientId(e.target.value)}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                    placeholder="Enter Instagram recipient ID"
                  />
                </div>
                
                <div>
                  <label htmlFor="topK" className="block text-sm font-medium text-gray-700">
                    Number of Results
                  </label>
                  <input
                    type="number"
                    id="topK"
                    value={topK}
                    onChange={(e) => setTopK(parseInt(e.target.value) || 5)}
                    min="1"
                    max="20"
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  />
                </div>
                
                <button
                  type="submit"
                  disabled={isLoading || !query.trim()}
                  className={`w-full bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors ${
                    (isLoading || !query.trim()) ? 'opacity-50 cursor-not-allowed' : ''
                  }`}
                >
                  {isLoading ? (
                    <div className="flex items-center justify-center">
                      <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                      Searching...
                    </div>
                  ) : 'Search'}
                </button>
                
                {error && (
                  <p className="text-sm text-red-500">{error}</p>
                )}
              </form>
              
              {/* Search Results */}
              {results.length > 0 && (
                <div className="mt-8 border rounded-lg p-4">
                  <h2 className="text-xl font-semibold mb-4">Search Results</h2>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Relevance
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Username
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Content
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Caption
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Date
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {results.map((result, index) => (
                          <tr key={index} className="hover:bg-gray-50">
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {(result.score * 100).toFixed(1)}%
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              @{result.username}
                            </td>
                            <td className="px-6 py-4 text-sm text-gray-500">
                              <div className="relative group">
                                <div className="max-w-xs truncate">
                                  {result.content || 'No content'}
                                </div>
                                <div className="absolute hidden group-hover:block z-50 w-64 p-2 mt-1 text-sm text-white bg-gray-800 rounded-lg shadow-lg">
                                  {result.content || 'No content'}
                                </div>
                              </div>
                            </td>
                            <td className="px-6 py-4 text-sm text-gray-500">
                              <div className="relative group">
                                <div className="max-w-xs truncate">
                                  {result.caption || 'No caption'}
                                </div>
                                <div className="absolute hidden group-hover:block z-50 w-64 p-2 mt-1 text-sm text-white bg-gray-800 rounded-lg shadow-lg">
                                  {result.caption || 'No caption'}
                                </div>
                              </div>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {new Date(result.timestamp).toLocaleDateString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
              
              {/* No Results */}
              {!isLoading && query && results.length === 0 && !error && (
                <div className="mt-8 border rounded-lg p-4 text-center text-gray-500">
                  No results found for "{query}"
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
} 