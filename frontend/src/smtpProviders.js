// Shared SMTP provider → {host, port, encryption} lookup, used by both the
// admin-level SMTP settings form (Settings.jsx) and the project-level
// "Use project SMTP" form (Projects.jsx) so the two never drift apart.
export const SMTP_PROVIDER_DEFAULTS = {
  gmail: { smtp_host: 'smtp.gmail.com', smtp_port: 587, encryption: 'starttls' },
  outlook: { smtp_host: 'smtp.office365.com', smtp_port: 587, encryption: 'starttls' },
  zoho: { smtp_host: 'smtp.zoho.com', smtp_port: 587, encryption: 'starttls' },
  custom: {},
}

export const SMTP_PROVIDER_OPTIONS = [
  { value: 'gmail', label: 'Gmail' },
  { value: 'outlook', label: 'Outlook / Office 365 (SMTP AUTH)' },
  { value: 'zoho', label: 'Zoho' },
  { value: 'custom', label: 'Custom' },
]

export function smtpProviderPasswordHint(provider) {
  if (provider === 'gmail') {
    return 'Requires a 16-character Google App Password, not your regular account password (Google disabled basic-auth SMTP).'
  }
  if (provider === 'outlook') {
    return 'SMTP AUTH is disabled by default on many Exchange Online tenants — the tenant admin must re-enable it, or use an app password if MFA is on. This is separate from the Office 365 Graph sender.'
  }
  return ''
}
