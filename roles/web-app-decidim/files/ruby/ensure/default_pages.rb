# nocheck: mirrored-unit-test - runs in the Decidim console against Decidim::StaticPage;
# the model only exists once Rails has booted
org = Decidim::Organization.first
Decidim::System::CreateDefaultPages.call(org)
puts "Default pages ensured: #{Decidim::StaticPage.where(organization: org).order(:slug).pluck(:slug).join(',')}"
