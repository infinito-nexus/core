org = Decidim::Organization.first
Decidim::System::CreateDefaultPages.call(org)
puts "Default pages ensured: #{Decidim::StaticPage.where(organization: org).order(:slug).pluck(:slug).join(',')}"
