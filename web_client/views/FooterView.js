import FooterView from 'girder/views/layout/FooterView';
import { restRequest, apiRoot } from 'girder/rest';
import { wrap } from 'girder/utilities/PluginUtils';

import LayoutFooterTemplate from '../templates/layoutFooter.pug';
import 'girder/stylesheets/layout/footer.styl';

wrap(FooterView, 'initialize', function (initialize, ...args) {
    this.aboutHref = 'https://wholetale.org/';
    this.contactHref = 'https://groups.google.com/forum/#!forum/wholetale';
    this.bugHref = 'https://github.com/whole-tale/whole-tale/issues/new';
    initialize.apply(this, args);

    if (!this.wtSettings) {
        restRequest({
            url: 'wholetale/settings',
            method: 'GET'
        }).done((resp) => {
            this.wtSettings = resp;
            this.aboutHref = resp['wholetale.about_href'];
            this.contactHref = resp['wholetale.contact_href'];
            this.bugHref = resp['wholetale.bug_href'];
            this.render();
        });
    }
});

wrap(FooterView, 'render', function (render) {
    this.$el.html(LayoutFooterTemplate({
        apiRoot: apiRoot,
        aboutHref: this.aboutHref,
        contactHref: this.contactHref,
        bugLink: this.bugHref
    }));
    return this;
});
