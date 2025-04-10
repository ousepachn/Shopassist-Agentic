'use client';

import { useAuth } from '@/contexts/AuthContext';
import { useRouter } from 'next/navigation';
import { useState, useEffect } from 'react';
import { 
  getFirestore, 
  collection, 
  getDocs, 
  doc, 
  getDoc,
  query,
  orderBy,
  Timestamp 
} from 'firebase/firestore';
import { db } from '@/lib/firebase'; // Import the initialized db instance

const API_BASE_URL = 'http://localhost:8000';

interface ApiErrorDetail {
  msg: string;
  type: string;
  loc: (string | number)[];
}

interface ApiError {
  detail: string | ApiErrorDetail[];
}

interface ScrapeStatus {
  status: string;
  total_posts?: number;
  current_post?: number;
  profile_name?: string;
  message?: string;
  error?: string;
}

interface ProcessingStatus {
  scraping: ScrapeStatus;
  ai_processing: ScrapeStatus;
}

type ProcessingOption = 'update_all' | 'update_remaining' | 'skip';

interface PostMetadata {
  caption: string;
  timestamp: string;
  media_type: string;
  permalink: string;
  media_url: string;
  ai_analysis?: {
    description?: string;
    style?: string;
    mood?: string;
  };
}

interface ScrapingResult {
  status: string;
  timestamp: Date;
  message: string;
  current_post: number;
  total_posts: number;
  metadata?: PostMetadata[];
}

export function Dashboard() {
  const { user, signOut } = useAuth();
  const router = useRouter();
  const [isLoading, setIsLoading] = useState({
    scrape: false,
    process: false,
    profiles: false
  });
  const [status, setStatus] = useState({
    scrape: '',
    process: ''
  });
  const [formData, setFormData] = useState({
    username: '',
    max_posts: 50,
    process_with_vertex_ai: false,
    processing_option: 'update_remaining' as ProcessingOption
  });
  const [apiStatus, setApiStatus] = useState<ProcessingStatus | null>(null);
  const [pollingInterval, setPollingInterval] = useState<NodeJS.Timeout | null>(null);
  const [availableProfiles, setAvailableProfiles] = useState<string[]>([]);
  const [selectedProfile, setSelectedProfile] = useState<string | null>(null);
  const [profileData, setProfileData] = useState<ScrapingResult | null>(null);

  // Fetch available profiles on component mount
  useEffect(() => {
    if (user) {
      fetchProfiles();
    }
  }, [user]);

  // Fetch profile data when a profile is selected
  useEffect(() => {
    if (selectedProfile && user) {
      fetchProfileData(selectedProfile);
    }
  }, [selectedProfile, user]);

  const fetchProfiles = async () => {
    try {
      setIsLoading(prev => ({ ...prev, profiles: true }));
      
      const scrapingResultsRef = collection(db, 'scraping_results');
      const q = query(scrapingResultsRef, orderBy('timestamp', 'desc'));
      const querySnapshot = await getDocs(q);
      
      const profiles = querySnapshot.docs.map(doc => doc.id);
      setAvailableProfiles(profiles);
    } catch (error) {
      console.error('Error fetching profiles:', error);
      setAvailableProfiles([]);
    } finally {
      setIsLoading(prev => ({ ...prev, profiles: false }));
    }
  };

  const fetchProfileData = async (username: string) => {
    if (!user) return;
    
    try {
      const docRef = doc(db, 'scraping_results', username);
      const docSnap = await getDoc(docRef);

      if (docSnap.exists()) {
        const rawData = docSnap.data();
        const data: ScrapingResult = {
          status: rawData.status || '',
          message: rawData.message || '',
          current_post: rawData.current_post || 0,
          total_posts: rawData.total_posts || 0,
          timestamp: rawData.timestamp instanceof Timestamp 
            ? rawData.timestamp.toDate() 
            : new Date(rawData.timestamp),
          metadata: rawData.metadata?.map((post: any) => ({
            ...post,
            timestamp: post.timestamp instanceof Timestamp 
              ? post.timestamp.toDate() 
              : new Date(post.timestamp)
          }))
        };
        setProfileData(data);
      } else {
        console.log('No data found for profile:', username);
        setProfileData(null);
      }
    } catch (error) {
      console.error('Error fetching profile data:', error);
      setProfileData(null);
    }
  };

  // Fetch status immediately when username changes
  useEffect(() => {
    if (formData.username) {
      fetchStatus(formData.username);
    }
  }, [formData.username]);

  const fetchStatus = async (username: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/status/${username}`);
      if (response.ok) {
        const data = await response.json();
        setApiStatus(data);
        
        // Stop polling if both processes are complete or failed
        if (pollingInterval && 
            (data.scraping.status === 'completed' || data.scraping.status === 'failed') &&
            (data.ai_processing.status === 'completed' || data.ai_processing.status === 'failed')) {
          clearInterval(pollingInterval);
          setPollingInterval(null);
        }
      } else {
        console.error('Error fetching status:', await response.text());
      }
    } catch (error) {
      console.error('Error fetching status:', error);
    }
  };

  // Start polling when a task is initiated
  const startStatusPolling = (username: string) => {
    // Fetch status immediately
    fetchStatus(username);

    // Clear any existing polling
    if (pollingInterval) {
      clearInterval(pollingInterval);
    }

    // Poll every 5 seconds
    const interval = setInterval(() => fetchStatus(username), 5000);
    setPollingInterval(interval);
  };

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingInterval) {
        clearInterval(pollingInterval);
      }
    };
  }, [pollingInterval]);

  const handleSignOut = async () => {
    try {
      await signOut();
      router.push('/login');
    } catch (error) {
      console.error('Error signing out:', error);
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? (e.target as HTMLInputElement).checked : 
              name === 'max_posts' ? parseInt(value) || 0 : value
    }));
  };

  const handleScrape = async () => {
    if (!formData.username) {
      setStatus(prev => ({ ...prev, scrape: 'Error: Username is required' }));
      return;
    }

    try {
      setIsLoading(prev => ({ ...prev, scrape: true }));
      setStatus(prev => ({ ...prev, scrape: 'Starting scrape...' }));
      
      const requestBody = {
        username: formData.username,
        max_posts: formData.max_posts,
        process_with_vertex_ai: formData.process_with_vertex_ai
      };
      
      console.log('Making scrape request:', {
        url: `${API_BASE_URL}/api/scrape`,
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: requestBody
      });
      
      const response = await fetch(`${API_BASE_URL}/api/scrape`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody)
      });

      const data = await response.json();
      console.log('Scrape response:', { status: response.status, data });

      if (!response.ok) {
        if (typeof data.detail === 'string') {
          throw new Error(data.detail);
        } else if (Array.isArray(data.detail)) {
          throw new Error(data.detail.map((err: ApiErrorDetail) => err.msg).join(', '));
        }
        throw new Error('Scraping failed');
      }

      setStatus(prev => ({ ...prev, scrape: 'Scraping started successfully!' }));
      startStatusPolling(formData.username);
    } catch (error: unknown) {
      console.error('Error during scraping:', error);
      const errorMessage = error instanceof Error ? error.message : 'Scraping failed';
      setStatus(prev => ({ ...prev, scrape: `Error: ${errorMessage}` }));
    } finally {
      setIsLoading(prev => ({ ...prev, scrape: false }));
    }
  };

  const handleProcessAI = async () => {
    if (!formData.username) {
      setStatus(prev => ({ ...prev, process: 'Error: Username is required' }));
      return;
    }

    try {
      setIsLoading(prev => ({ ...prev, process: true }));
      setStatus(prev => ({ ...prev, process: 'Starting AI processing...' }));
      
      const response = await fetch(`${API_BASE_URL}/api/process-ai`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username: formData.username,
          processing_option: formData.processing_option
        })
      });

      const data = await response.json();

      if (!response.ok) {
        if (typeof data.detail === 'string') {
          throw new Error(data.detail);
        } else if (Array.isArray(data.detail)) {
          throw new Error(data.detail.map((err: ApiErrorDetail) => err.msg).join(', '));
        }
        throw new Error('AI processing failed');
      }

      setStatus(prev => ({ ...prev, process: 'AI processing started successfully!' }));
      startStatusPolling(formData.username);
    } catch (error: unknown) {
      console.error('Error during AI processing:', error);
      const errorMessage = error instanceof Error ? error.message : 'AI processing failed';
      setStatus(prev => ({ ...prev, process: `Error: ${errorMessage}` }));
    } finally {
      setIsLoading(prev => ({ ...prev, process: false }));
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'text-green-600';
      case 'failed':
        return 'text-red-600';
      case 'not_started':
        return 'text-gray-600';
      default:
        return 'text-yellow-600';
    }
  };

  const isProcessing = (status?: string): boolean => {
    return Boolean(status && !['completed', 'failed', 'not_started'].includes(status));
  };

  return (
    <main className="min-h-screen bg-gray-100">
      <div className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        <div className="px-4 py-6 sm:px-0">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex justify-between items-center mb-6">
              <h1 className="text-3xl font-bold text-gray-900">
                ShopAssist Instagram Scraper
              </h1>
              <button
                onClick={handleSignOut}
                className="bg-red-500 text-white px-4 py-2 rounded hover:bg-red-600 transition-colors"
              >
                Sign Out
              </button>
            </div>
            <div className="space-y-6">
              <p className="text-gray-600">Welcome to the dashboard</p>
              <p className="text-sm text-gray-500">Logged in as: {user?.email}</p>
              
              <div className="space-y-4 mb-6">
                <div>
                  <label htmlFor="username" className="block text-sm font-medium text-gray-700">
                    Instagram Username
                  </label>
                  <input
                    type="text"
                    id="username"
                    name="username"
                    value={formData.username}
                    onChange={handleInputChange}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                    placeholder="Enter Instagram username"
                  />
                </div>
                <div>
                  <label htmlFor="max_posts" className="block text-sm font-medium text-gray-700">
                    Maximum Posts to Scrape
                  </label>
                  <input
                    type="number"
                    id="max_posts"
                    name="max_posts"
                    value={formData.max_posts}
                    onChange={handleInputChange}
                    min="1"
                    max="100"
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  />
                </div>
                <div className="flex items-center">
                  <input
                    type="checkbox"
                    id="process_with_vertex_ai"
                    name="process_with_vertex_ai"
                    checked={formData.process_with_vertex_ai}
                    onChange={handleInputChange}
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                  />
                  <label htmlFor="process_with_vertex_ai" className="ml-2 block text-sm text-gray-700">
                    Process with Vertex AI
                  </label>
                </div>
              </div>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="border rounded-lg p-4">
                  <h2 className="text-xl font-semibold mb-4">Instagram Scraping</h2>
                  <button
                    onClick={handleScrape}
                    disabled={isLoading.scrape || !formData.username || isProcessing(apiStatus?.scraping.status)}
                    className={`w-full bg-blue-500 text-white px-4 py-2 rounded hover:bg-blue-600 transition-colors ${
                      (isLoading.scrape || !formData.username || isProcessing(apiStatus?.scraping.status)) ? 'opacity-50 cursor-not-allowed' : ''
                    }`}
                  >
                    {isProcessing(apiStatus?.scraping.status) ? (
                      <div className="flex items-center justify-center">
                        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                        Processing...
                      </div>
                    ) : isLoading.scrape ? 'Starting...' : 'Start Scraping'}
                  </button>
                  {status.scrape && (
                    <p className={`mt-2 text-sm ${
                      status.scrape.includes('Error') ? 'text-red-500' : 'text-green-500'
                    }`}>
                      {status.scrape}
                    </p>
                  )}
                </div>

                <div className="border rounded-lg p-4">
                  <h2 className="text-xl font-semibold mb-4">AI Processing</h2>
                  
                  {/* AI Processing Options */}
                  <div className="mb-4">
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Processing Option
                    </label>
                    <select
                      name="processing_option"
                      value={formData.processing_option}
                      onChange={handleInputChange}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                    >
                      <option value="update_all">Update All Posts</option>
                      <option value="update_remaining">Update Remaining Posts</option>
                      <option value="skip">Skip Processing</option>
                    </select>
                  </div>

                  <button
                    onClick={handleProcessAI}
                    disabled={isLoading.process || !formData.username}
                    className={`w-full bg-purple-500 text-white px-4 py-2 rounded hover:bg-purple-600 transition-colors ${
                      (isLoading.process || !formData.username) ? 'opacity-50 cursor-not-allowed' : ''
                    }`}
                  >
                    {isLoading.process ? 'Processing...' : 'Start AI Processing'}
                  </button>
                  {status.process && (
                    <p className={`mt-2 text-sm ${
                      status.process.includes('Error') ? 'text-red-500' : 'text-green-500'
                    }`}>
                      {status.process}
                    </p>
                  )}
                </div>
              </div>

              {/* Profile Selection and Data Table */}
              <div className="mt-8 border rounded-lg p-4">
                <h2 className="text-xl font-semibold mb-4">Scraping Results</h2>
                
                {/* Profile Selection */}
                <div className="mb-6">
                  <label htmlFor="profile-select" className="block text-sm font-medium text-gray-700 mb-2">
                    Select Profile
                  </label>
                  <select
                    id="profile-select"
                    value={selectedProfile || ''}
                    onChange={(e) => setSelectedProfile(e.target.value || null)}
                    className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  >
                    <option value="">Select a profile</option>
                    {availableProfiles.map((profile) => (
                      <option key={profile} value={profile}>
                        @{profile}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Data Table */}
                {selectedProfile && profileData?.metadata && (
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Title
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Type
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Created Date
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Last Scraped
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            AI Description
                          </th>
                          <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Link
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {profileData.metadata.map((post, index) => (
                          <tr key={index} className="hover:bg-gray-50">
                            <td className="px-6 py-4 text-sm text-gray-500">
                              <div className="max-w-xs truncate">
                                {post.caption || 'No title'}
                              </div>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {post.media_type}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {new Date(post.timestamp).toLocaleDateString()}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {profileData.timestamp.toLocaleDateString()}
                            </td>
                            <td className="px-6 py-4 text-sm text-gray-500">
                              <div className="max-w-xs truncate">
                                {post.ai_analysis?.description || 'No AI analysis'}
                              </div>
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              <a
                                href={post.permalink}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-blue-600 hover:text-blue-800"
                              >
                                View Post
                              </a>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Loading State */}
                {isLoading.profiles && (
                  <div className="flex justify-center items-center py-8">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                  </div>
                )}

                {/* No Data State */}
                {selectedProfile && !profileData?.metadata && !isLoading.profiles && (
                  <div className="text-center py-8 text-gray-500">
                    No data available for this profile
                  </div>
                )}
              </div>

              {/* Status and Logs Section */}
              <div className="mt-8 border rounded-lg p-4">
                <h2 className="text-xl font-semibold mb-4">Process Status</h2>
                <div className="space-y-4">
                  {!formData.username ? (
                    <p className="text-sm text-gray-500">Enter an Instagram username to see status</p>
                  ) : !apiStatus ? (
                    <p className="text-sm text-gray-500">No active processes for @{formData.username}</p>
                  ) : (
                    <>
                      <div className="grid grid-cols-1 gap-4">
                        <div className="border rounded-lg p-4">
                          <h3 className="text-sm font-medium text-gray-700 mb-2">Scraping Status</h3>
                          <div className="space-y-2">
                            <p className={`text-sm ${getStatusColor(apiStatus.scraping.status)}`}>
                              Status: {apiStatus.scraping.status.charAt(0).toUpperCase() + apiStatus.scraping.status.slice(1)}
                            </p>
                            {apiStatus.scraping.message && (
                              <p className="text-sm text-gray-600">{apiStatus.scraping.message}</p>
                            )}
                            {apiStatus.scraping.total_posts !== undefined && (
                              <div className="w-full bg-gray-200 rounded-full h-2.5 dark:bg-gray-700">
                                <div 
                                  className="bg-blue-600 h-2.5 rounded-full transition-all duration-500"
                                  style={{ 
                                    width: `${(apiStatus.scraping.current_post || 0) / apiStatus.scraping.total_posts * 100}%` 
                                  }}
                                ></div>
                              </div>
                            )}
                            {apiStatus.scraping.error && (
                              <p className="text-sm text-red-500">{apiStatus.scraping.error}</p>
                            )}
                          </div>
                        </div>

                        <div className="border rounded-lg p-4">
                          <h3 className="text-sm font-medium text-gray-700 mb-2">AI Processing Status</h3>
                          <div className="space-y-2">
                            <p className={`text-sm ${getStatusColor(apiStatus.ai_processing.status)}`}>
                              Status: {apiStatus.ai_processing.status.charAt(0).toUpperCase() + apiStatus.ai_processing.status.slice(1)}
                            </p>
                            {apiStatus.ai_processing.message && (
                              <p className="text-sm text-gray-600">{apiStatus.ai_processing.message}</p>
                            )}
                            {apiStatus.ai_processing.error && (
                              <p className="text-sm text-red-500">{apiStatus.ai_processing.error}</p>
                            )}
                          </div>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
} 