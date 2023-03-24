import _ from 'underscore';

import { restRequest } from 'girder/rest';
import { wrap } from 'girder/utilities/PluginUtils';
import { getCurrentUser } from 'girder/auth';

import HierarchyWidget from 'girder/views/widgets/HierarchyWidget';

import WholeTaleHierarchyWidget from '../templates/WholeTaleHierarchyWidget.pug';

wrap(HierarchyWidget, 'render', function (render) {
    var widget = this;

    if (getCurrentUser() && widget.parentModel.resourceName === 'folder') {
        render.call(widget);
        $(WholeTaleHierarchyWidget()).prependTo(widget.$('.g-folder-header-buttons'));
        document.getElementsByClassName('g-createTale-button')[0].style.display = 'inline';
    } else {
        render.call(widget);
    }
});

function _analyzeInWT(e) {
    restRequest({
        path: 'folder/' + this.parentModel.id + '/dataset',
        type: 'GET',
    }).done(_.bind(function (dataset) {
        var dashboardUrl = window.location.origin.replace("girder", "dashboard") + '/mine';
        const params = new URLSearchParams();
        params.set('name', 'My Tale');
        params.set('asTale', false);
        params.set('dataSet', JSON.stringify(dataset));
        window.location.assign(dashboardUrl + `?${params.toString()}`);
    }, this));
}

HierarchyWidget.prototype.events['click .g-createTale-button'] = _analyzeInWT;
