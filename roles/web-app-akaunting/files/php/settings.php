// nocheck: mirrored-unit-test - evaluated by artisan tinker against the live company settings store; files/playwright/test-design.js asserts its effect on the running app
// Tinker snippet for `artisan tinker --execute`, no opening tag.
//
// Args (environment):
//   DESIGN_DOCUMENT_COLOR: hex literal for invoice.color and bill.color of every company; empty removes what an earlier run wrote.
//   DESIGN_TITLE: company.name of the installed (first) company; empty restores COMPANY_NAME_DEFAULT where an earlier run wrote the title.
//   COMPANY_NAME_DEFAULT: company name the install wrote, which the title may replace.
//
// Output: one line per company and key, one wizard line and one company.name line, each ending in CHANGED or UNCHANGED, then DONE.
$color = (string) getenv('DESIGN_DOCUMENT_COLOR');
$title = (string) getenv('DESIGN_TITLE');
$installed = (string) getenv('COMPANY_NAME_DEFAULT');
foreach (\App\Models\Common\Company::all() as $company) {
    $company->makeCurrent(true);
    foreach (['invoice.color', 'bill.color'] as $key) {
        $mark = 'infinito.design.' . $key;
        $current = (string) setting()->get($key);
        $owned = $current === (string) setting()->getFallback($key) || (setting()->has($mark) && $current === (string) setting()->get($mark));
        $state = 'UNCHANGED';
        if ($color !== '' && $owned && $current !== $color) {
            setting()->set($key, $color);
            setting()->set($mark, $color);
            $state = 'CHANGED';
        } elseif ($color === '' && setting()->has($mark)) {
            if ($owned) {
                setting()->forget($key);
            }
            setting()->forget($mark);
            $state = 'CHANGED';
        }
        setting()->save();
        echo "company {$company->id} {$key} {$state}\n";
    }
}
$first = \App\Models\Common\Company::orderBy('id')->first();
$wizard = 'UNCHANGED';
if ($first) {
    $first->makeCurrent(true);
    if ((string) setting()->get('wizard.completed') !== '1') {
        setting()->set('wizard.completed', '1');
        setting()->save();
        $wizard = 'CHANGED';
    }
    $mark = 'infinito.design.company.name';
    $current = (string) setting()->get('company.name');
    $owned = $current === $installed || (setting()->has($mark) && $current === (string) setting()->get($mark));
    $state = 'UNCHANGED';
    if ($title !== '' && $owned && $current !== $title) {
        setting()->set('company.name', $title);
        setting()->set($mark, $title);
        $state = 'CHANGED';
    } elseif ($title === '' && setting()->has($mark)) {
        if ($owned && $current !== $installed) {
            setting()->set('company.name', $installed);
        }
        setting()->forget($mark);
        $state = 'CHANGED';
    }
    setting()->save();
    echo "company {$first->id} company.name {$state}\n";
}
echo "wizard {$wizard}\n";
echo "DONE\n";
