import HeaderUserView from 'girder/views/layout/HeaderUserView';
import { getCurrentUser } from 'girder/auth';
import { wrap } from 'girder/utilities/PluginUtils';
import { restRequest, getApiRoot } from 'girder/rest';

import HeaderLogoTemplate from '../templates/headerLogo.pug';
import HeaderLinkTemplate from '../templates/headerLink.pug';
import HeaderUserViewMenuTemplate from '../templates/headerUserViewMenu.pug';
import '../stylesheets/header.styl';

/**
 * Customize the header view
 */
wrap(HeaderUserView, 'render', function (render) {
    render.call(this);

    // Update based on branding configuration
    if (!this.branded) {
        restRequest({
            method: 'GET',
            url: 'wholetale/settings'
        }).done((resp) => {
            let logoUrl = '';
            if (resp['wholetale.logo']) {
                logoUrl = `${getApiRoot()}/${resp['wholetale.logo']}`;
            }
            let dashboardUrl = resp['wholetale.dashboard_url'];
            let title = resp['wholetale.dashboard_link_title'];
            let bannerColor = resp['core.banner_color'];

            if (!$('.g-app-logo').length) {
                $('.g-app-title').prepend(HeaderLogoTemplate({ logoUrl: logoUrl }));
            }
            if (!$('.g-dashboard-link').length) {
                $('.g-quick-search-form').after(HeaderLinkTemplate({
                    dashboardUrl: dashboardUrl,
                    title: title }));
                document.getElementsByClassName('g-header-wrapper')[0].style.backgroundColor = bannerColor;
            }
            this.branded = true;
        });
    }

    // Add an entry to the user dropdown menu to navigate to user's ext keys
    var currentUser = getCurrentUser();
    if (currentUser) {
        this.$('#g-user-action-menu>ul').prepend(HeaderUserViewMenuTemplate({
            href: '#ext_keys'
        }));
    }
    return this;
});
