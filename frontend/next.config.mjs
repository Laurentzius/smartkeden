/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Ensure we can proxy API calls or allow absolute external URLs
  async rewrites() {
    const backendUrl = process.env.BACKEND_INTERNAL_URL || 'http://localhost:8000';
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`, // Proxy to FastAPI
      },
    ];
  },
  experimental: {
    proxyTimeout: 120_000,
  },
};
export default nextConfig;
