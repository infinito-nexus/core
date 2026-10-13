<?php

// nocheck: mirrored-unit-test - a Matomo theme plugin; Matomo loads it from its plugins
// directory and calls it from the Theme.configureThemeVariables event of a live installation

namespace Piwik\Plugins\InfinitoDesign;

use Piwik\Plugin\ThemeStyles;

class InfinitoDesign extends \Piwik\Plugin
{
    private const TOKENS = [
        'colorBrand' => 'var(--design-primary)',
        'colorNewBrand' => 'var(--design-primary)',
        'colorBaseSeries' => 'var(--design-primary)',
        'colorBrandContrast' => 'var(--design-on-primary)',
        'colorFocusRing' => 'var(--design-focus, var(--design-link))',
        'colorFocusRingAlternative' => 'var(--design-focus, var(--design-link))',
        'colorTextHighContrast' => 'var(--design-text)',
        'colorText' => 'var(--design-text)',
        'colorTextContrast' => 'var(--design-text)',
        'colorHeadlineAlternative' => 'var(--design-text)',
        'colorMenuContrastText' => 'var(--design-text)',
        'colorMenuContrastTextSelected' => 'var(--design-text)',
        'colorWidgetTitleText' => 'var(--design-text)',
        'colorTextLight' => 'var(--design-text-muted)',
        'colorTextLighter' => 'var(--design-text-muted)',
        'colorTextOnDisabled' => 'var(--design-text-muted)',
        'colorTextPlaceholder' => 'var(--design-text-muted)',
        'colorTextDisabled' => 'var(--design-text-muted)',
        'colorHeaderText' => 'var(--design-text-muted)',
        'colorLink' => 'var(--design-link)',
        'colorMenuContrastTextActive' => 'var(--design-link)',
        'colorBackgroundBase' => 'var(--design-surface-1)',
        'colorBackgroundContrast' => 'var(--design-surface-2)',
        'colorHeaderBackground' => 'var(--design-surface-2)',
        'colorMenuContrastBackground' => 'var(--design-surface-2)',
        'colorWidgetBackground' => 'var(--design-surface-2)',
        'colorWidgetTitleBackground' => 'var(--design-surface-2)',
        'colorWidgetExportedBackgroundBase' => 'var(--design-surface-2)',
        'colorBackgroundTinyContrast' => 'var(--design-surface-3)',
        'colorBackgroundDisabled' => 'var(--design-surface-3)',
        'colorMenuContrastBackgroundHover' => 'var(--design-surface-hover)',
        'colorBackgroundLowContrast' => 'var(--design-surface-active)',
        'colorBackgroundHighContrast' => 'var(--design-neutral-900)',
        'colorTextInvert' => 'var(--design-neutral-200)',
        'colorTextInvertLight' => 'var(--design-neutral-200)',
        'colorTextInvertContrast' => 'var(--design-neutral-50)',
        'colorCode' => 'var(--design-neutral-50)',
        'colorCodeBackground' => 'var(--design-neutral-900)',
        'colorBorder' => 'var(--design-border-strong)',
        'colorBorderLight' => 'var(--design-border-strong)',
        'colorBorderAlternative' => 'var(--design-border)',
        'colorWidgetBorder' => 'var(--design-border)',
        'colorBoxShadow' => 'color-mix(in srgb, var(--design-neutral-950) 12%, transparent)',
        'shadowOverlay' => 'var(--design-shadow-3)',
    ];

    public function registerEvents()
    {
        return [
            'Theme.configureThemeVariables' => 'configureThemeVariables',
        ];
    }

    public function configureThemeVariables(ThemeStyles $vars): void
    {
        foreach (self::TOKENS as $property => $value) {
            $vars->$property = [$value, $value];
        }
    }
}
