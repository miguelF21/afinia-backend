const getApiUrl = (defaultUrl: string): string => {
  if (typeof window !== 'undefined' && window.localStorage) {
    const override = window.localStorage.getItem('AFINIA_API_URL');
    if (override) return override;
  }
  return defaultUrl;
};

export const environment = {
  production: true,
  apiUrl: getApiUrl('https://afinia-backend.onrender.com/api/v1'),
  legalTermsVersion: 'v1-draft',
  legalPrivacyVersion: 'v1-draft'
};
