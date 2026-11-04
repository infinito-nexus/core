// nocheck: mirrored-unit-test - evaluated by artisan tinker against the live company media store; files/playwright/test-design.js asserts its effect on the running app
// Tinker snippet for `artisan tinker --execute`, no opening tag.
//
// Args (environment):
//   DESIGN_LOGO_PNG: base64 PNG for company.logo of the installed (first) company; empty removes the logo an earlier run attached.
//
// Output: one company.logo line ending in CHANGED or UNCHANGED, then DONE.
$png = (string) base64_decode((string) getenv('DESIGN_LOGO_PNG'), true);
$first = \App\Models\Common\Company::orderBy('id')->first();
if ($first) {
    $first->makeCurrent(true);
    $mark = 'infinito.design.company.logo';
    $owner = (string) setting()->get($mark);
    $current = (string) setting()->get('company.logo');
    $ours = $owner !== '' ? \App\Models\Common\Media::find($owner) : null;
    $attached = $owner !== '' && $current === $owner;
    $state = 'UNCHANGED';
    if ($png !== '' && ($attached || ($owner === '' && $current === ''))) {
        $same = $attached && $ours && $ours->fileExists() && hash_equals(hash('sha256', $ours->contents()), hash('sha256', $png));
        if (! $same) {
            $media = \MediaUploader::makePrivate()
                ->beforeSave(function (\App\Models\Common\Media $media) use ($first) {
                    $media->company_id = $first->id;
                    $media->created_from = source_name();
                })
                ->fromString($png)
                ->toDirectory(\App\Utilities\Date::now()->format('Y/m/d') . '/' . $first->id . '/settings')
                ->useFilename('infinito-design-logo')
                ->onDuplicateIncrement()
                ->upload();
            $first->attachMedia($media, 'company.logo');
            setting()->set('company.logo', $media->id);
            setting()->set($mark, $media->id);
            if ($ours) {
                $ours->forceDelete();
            }
            $state = 'CHANGED';
        }
    } elseif ($png === '' && $owner !== '') {
        if ($attached) {
            setting()->forget('company.logo');
        }
        if ($ours) {
            $ours->forceDelete();
        }
        setting()->forget($mark);
        $state = 'CHANGED';
    }
    setting()->save();
    echo "company {$first->id} company.logo {$state}\n";
}
echo "DONE\n";
