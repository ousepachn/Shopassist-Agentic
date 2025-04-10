import './globals.css'

export const metadata = {
  title: 'ShopAssist Instagram Scraper',
  description: 'Instagram content scraping and analysis tool',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>
        {children}
      </body>
    </html>
  )
} 